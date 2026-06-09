import click
import time
import sys
import signal
from datetime import datetime, date, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.panel import Panel

from ..database import get_connection
from ..utils import format_duration, format_datetime, parse_date
from ..config import get_config_value

console = Console()

PAUSED_POMODORO_ID = None


def start_pomodoro(task_id=None, duration=None):
    if duration is None:
        duration = get_config_value('pomodoro_duration')
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO pomodoros (task_id, start_time, duration, status)
    VALUES (?, CURRENT_TIMESTAMP, ?, 'running')
    ''', (task_id, duration))
    
    pomodoro_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return pomodoro_id, duration


def pause_pomodoro(pomodoro_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    UPDATE pomodoros 
    SET status = 'paused', end_time = CURRENT_TIMESTAMP
    WHERE id = ? AND status = 'running'
    ''', (pomodoro_id,))
    
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    
    return updated


def resume_pomodoro(pomodoro_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM pomodoros WHERE id = ?', (pomodoro_id,))
    pomo = cursor.fetchone()
    
    if not pomo or pomo['status'] != 'paused':
        conn.close()
        return False
    
    end_time = datetime.fromisoformat(pomo['end_time'])
    now = datetime.now()
    paused_duration = (now - end_time).total_seconds() / 60
    
    new_duration = pomo['duration'] + int(paused_duration)
    
    cursor.execute('''
    UPDATE pomodoros 
    SET status = 'running', duration = ?, start_time = CURRENT_TIMESTAMP, end_time = NULL
    WHERE id = ?
    ''', (new_duration, pomodoro_id))
    
    conn.commit()
    conn.close()
    
    return True, new_duration


def complete_pomodoro(pomodoro_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM pomodoros WHERE id = ?', (pomodoro_id,))
    pomo = cursor.fetchone()
    
    if not pomo:
        conn.close()
        return False
    
    cursor.execute('''
    UPDATE pomodoros 
    SET status = 'completed', end_time = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (pomodoro_id,))
    
    if pomo['task_id']:
        cursor.execute('''
        UPDATE tasks 
        SET actual_time = COALESCE(actual_time, 0) + ?,
            status = CASE WHEN status = 'pending' THEN 'in_progress' ELSE status END
        WHERE id = ?
        ''', (pomo['duration'], pomo['task_id']))
    
    conn.commit()
    conn.close()
    
    return True


def add_interruption(pomodoro_id, note=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    UPDATE pomodoros 
    SET interruptions = COALESCE(interruptions, 0) + 1,
        interruption_notes = COALESCE(interruption_notes, '') || ?
    WHERE id = ? AND status IN ('running', 'paused')
    ''', (f"\n- {datetime.now().strftime('%H:%M')}: {note or '未记录原因'}", pomodoro_id))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return updated


def get_current_pomodoro():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT p.*, t.title as task_title
    FROM pomodoros p
    LEFT JOIN tasks t ON p.task_id = t.id
    WHERE p.status IN ('running', 'paused')
    ORDER BY p.id DESC
    LIMIT 1
    ''')
    
    pomo = cursor.fetchone()
    conn.close()
    
    return pomo


def get_pomodoros_by_date(start_date, end_date=None):
    if end_date is None:
        end_date = start_date
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT p.*, t.title as task_title
    FROM pomodoros p
    LEFT JOIN tasks t ON p.task_id = t.id
    WHERE DATE(p.start_time) BETWEEN ? AND ?
    ORDER BY p.start_time DESC
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def run_pomodoro_timer(pomodoro_id, duration, task_title=None):
    total_seconds = duration * 60
    
    console.print(f"\n[bold]🍅 番茄钟开始！[/bold]")
    if task_title:
        console.print(f"任务: {task_title}")
    console.print(f"时长: {duration} 分钟\n")
    
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("专注中...", total=total_seconds)
        
        try:
            for second in range(total_seconds):
                if get_global_pause_flag():
                    console.print("\n[yellow]⏸️  番茄钟已暂停[/yellow]")
                    return 'paused'
                
                progress.update(task, advance=1)
                time.sleep(1)
            
            console.print("\n[green]🎉 番茄钟完成！[/green]")
            complete_pomodoro(pomodoro_id)
            return 'completed'
            
        except KeyboardInterrupt:
            console.print("\n[yellow]⏸️  检测到中断，暂停番茄钟[/yellow]")
            pause_pomodoro(pomodoro_id)
            return 'paused'


_global_pause_flag = [False]


def get_global_pause_flag():
    return _global_pause_flag[0]


def set_global_pause_flag(value):
    _global_pause_flag[0] = value


@click.group()
def focus():
    """番茄钟专注"""
    pass


@focus.command()
@click.option('-t', '--task', 'task_id', type=int, help='关联的任务ID')
@click.option('-d', '--duration', type=int, help='番茄钟时长（分钟）')
def start(task_id, duration):
    """开始番茄钟"""
    current = get_current_pomodoro()
    if current and current['status'] == 'running':
        console.print(f"[yellow]已有运行中的番茄钟 #id{current['id']}[/yellow]")
        return
    
    pomo_id, dur = start_pomodoro(task_id, duration)
    
    task_title = None
    if task_id:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT title FROM tasks WHERE id = ?', (task_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            task_title = row['title']
    
    result = run_pomodoro_timer(pomo_id, dur, task_title)
    
    if result == 'completed':
        short_break = get_config_value('short_break_duration')
        console.print(f"\n☕ 休息 {short_break} 分钟吧！")


@focus.command()
def pause():
    """暂停当前番茄钟"""
    current = get_current_pomodoro()
    if not current or current['status'] != 'running':
        console.print("[yellow]没有运行中的番茄钟[/yellow]")
        return
    
    set_global_pause_flag(True)
    time.sleep(1.5)
    
    if pause_pomodoro(current['id']):
        console.print(f"[green]✓ 番茄钟 #{current['id']} 已暂停[/green]")
    set_global_pause_flag(False)


@focus.command()
def resume():
    """恢复暂停的番茄钟"""
    current = get_current_pomodoro()
    if not current or current['status'] != 'paused':
        console.print("[yellow]没有暂停中的番茄钟[/yellow]")
        return
    
    result = resume_pomodoro(current['id'])
    if result:
        _, new_duration = result
        
        task_title = current['task_title']
        start_time = datetime.fromisoformat(current['start_time'])
        end_time = datetime.fromisoformat(current['end_time'])
        paused_minutes = int((datetime.now() - end_time).total_seconds() / 60)
        
        console.print(f"[green]✓ 番茄钟 #{current['id']} 已恢复[/green]")
        console.print(f"暂停时长: {paused_minutes} 分钟，已追加到总时长")
        
        run_pomodoro_timer(current['id'], new_duration, task_title)


@focus.command()
@click.option('-n', '--note', help='干扰原因记录')
def interrupt(note):
    """记录干扰"""
    current = get_current_pomodoro()
    if not current or current['status'] not in ('running', 'paused'):
        console.print("[yellow]没有进行中的番茄钟[/yellow]")
        return
    
    if add_interruption(current['id'], note):
        console.print(f"[yellow]⚠️  已记录干扰 #{current['id']}[/yellow]")
    else:
        console.print("[red]✗ 记录失败[/red]")


@focus.command()
@click.argument('pomodoro_id', type=int, required=False)
def stop(pomodoro_id):
    """停止番茄钟"""
    if pomodoro_id is None:
        current = get_current_pomodoro()
        if current:
            pomodoro_id = current['id']
        else:
            console.print("[yellow]没有进行中的番茄钟[/yellow]")
            return
    
    if complete_pomodoro(pomodoro_id):
        console.print(f"[green]✓ 番茄钟 #{pomodoro_id} 已完成[/green]")
    else:
        console.print(f"[red]✗ 番茄钟 #{pomodoro_id} 不存在[/red]")


@focus.command()
def status():
    """查看当前番茄钟状态"""
    current = get_current_pomodoro()
    
    if not current:
        console.print("[yellow]没有进行中的番茄钟[/yellow]")
        return
    
    status_map = {
        'running': '🏃 运行中',
        'paused': '⏸️  暂停中',
        'completed': '✅ 完成',
        'cancelled': '❌ 取消'
    }
    
    console.print(f"[bold]🍅 当前番茄钟[/bold]")
    console.print(f"ID: #{current['id']}")
    console.print(f"状态: {status_map.get(current['status'], current['status'])}")
    if current['task_title']:
        console.print(f"任务: {current['task_title']}")
    console.print(f"时长: {format_duration(current['duration'])}")
    console.print(f"开始时间: {format_datetime(datetime.fromisoformat(current['start_time']))}")
    
    if current['interruptions']:
        console.print(f"[yellow]干扰次数: {current['interruptions']}[/yellow]")
        if current['interruption_notes']:
            console.print(f"干扰记录: {current['interruption_notes']}")


@focus.command()
@click.option('-d', '--date', 'date_str', help='查看指定日期 (YYYY-MM-DD, today)')
@click.option('-w', '--week', is_flag=True, help='查看本周统计')
def log(date_str, week):
    """查看番茄钟历史"""
    if week:
        from ..utils import get_week_range
        start_date, end_date = get_week_range()
    else:
        target_date = parse_date(date_str) if date_str else date.today()
        start_date = end_date = target_date
    
    pomodoros = get_pomodoros_by_date(start_date, end_date)
    
    if not pomodoros:
        console.print("[yellow]没有找到番茄钟记录[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("状态", width=10)
    table.add_column("任务", overflow="fold")
    table.add_column("时长", width=10)
    table.add_column("干扰", width=8)
    table.add_column("开始时间", width=20)
    
    total_duration = 0
    completed_count = 0
    
    for pomo in pomodoros:
        status_label = {
            'running': '🏃 运行中',
            'paused': '⏸️  暂停中',
            'completed': '✅ 完成',
            'cancelled': '❌ 取消'
        }.get(pomo['status'], pomo['status'])
        
        if pomo['status'] == 'completed':
            completed_count += 1
            total_duration += pomo['duration']
        
        table.add_row(
            str(pomo['id']),
            status_label,
            pomo['task_title'] or '-',
            format_duration(pomo['duration']),
            str(pomo['interruptions']) if pomo['interruptions'] else '-',
            format_datetime(datetime.fromisoformat(pomo['start_time']))
        )
    
    console.print(table)
    
    if week:
        console.print(f"\n📊 本周统计:")
    else:
        console.print(f"\n📊 当日统计:")
    console.print(f"  完成番茄钟: {completed_count} 个")
    console.print(f"  总专注时长: {format_duration(total_duration)}")
    
    daily_goal = get_config_value('daily_pomodoro_goal')
    if not week and date_str is None:
        if completed_count >= daily_goal:
            console.print(f"  [green]🎯 已达成每日目标 ({daily_goal}个)[/green]")
        else:
            remaining = daily_goal - completed_count
            console.print(f"  [yellow]距每日目标还差 {remaining} 个[/yellow]")
