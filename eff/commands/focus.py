import click
import time
import sys
import threading
import select
from datetime import datetime, date, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text

from ..database import get_connection
from ..utils import format_duration, format_datetime, format_date, parse_date
from ..config import get_config_value

console = Console()


class PomodoroSession:
    def __init__(self, task_id=None, duration=None):
        self.task_id = task_id
        self.task_title = None
        self.duration = duration or get_config_value('pomodoro_duration')
        self.total_seconds = self.duration * 60
        self.remaining_seconds = self.total_seconds
        self.pomodoro_id = None
        self.status = 'idle'
        self.interruptions = 0
        self.interruption_notes = []
        self.start_time = None
        self.pause_time = None
        self.total_paused_seconds = 0
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._command = None
        
    def validate_task(self):
        if self.task_id is None:
            return True
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (self.task_id,))
        task = cursor.fetchone()
        conn.close()
        
        if not task:
            return False
        
        self.task_title = task['title']
        return True
    
    def create_pomodoro_record(self):
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO pomodoros (task_id, start_time, duration, status)
        VALUES (?, CURRENT_TIMESTAMP, ?, 'running')
        ''', (self.task_id, self.duration))
        
        self.pomodoro_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        self.start_time = datetime.now()
        return True
    
    def update_pomodoro_status(self, status, end_time=None):
        conn = get_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        updates.append('status = ?')
        params.append(status)
        
        if end_time:
            updates.append('end_time = ?')
            params.append(end_time.isoformat())
        
        if self.interruptions > 0:
            updates.append('interruptions = ?')
            params.append(self.interruptions)
        
        if self.interruption_notes:
            updates.append('interruption_notes = ?')
            params.append('\n'.join(self.interruption_notes))
        
        params.append(self.pomodoro_id)
        query = f"UPDATE pomodoros SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        
        conn.commit()
        conn.close()
    
    def add_interruption(self, note=None):
        self.interruptions += 1
        timestamp = datetime.now().strftime('%H:%M')
        note_text = note or '未记录原因'
        self.interruption_notes.append(f"- {timestamp}: {note_text}")
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE pomodoros 
        SET interruptions = COALESCE(interruptions, 0) + 1,
            interruption_notes = COALESCE(interruption_notes, '') || ?
        WHERE id = ?
        ''', (f"\n- {timestamp}: {note_text}", self.pomodoro_id))
        conn.commit()
        conn.close()
    
    def complete(self):
        actual_duration = (self.total_seconds - self.remaining_seconds) // 60
        actual_duration = max(1, actual_duration)
        
        end_time = datetime.now()
        self.update_pomodoro_status('completed', end_time)
        
        if self.task_id:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE tasks 
            SET actual_time = COALESCE(actual_time, 0) + ?,
                status = CASE WHEN status = 'pending' THEN 'in_progress' ELSE status END
            WHERE id = ?
            ''', (actual_duration, self.task_id))
            conn.commit()
            conn.close()
        
        return actual_duration
    
    def cancel(self):
        actual_duration = (self.total_seconds - self.remaining_seconds) // 60
        actual_duration = max(1, actual_duration)
        
        end_time = datetime.now()
        self.update_pomodoro_status('cancelled', end_time)
        
        if self.task_id and actual_duration > 0:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE tasks 
            SET actual_time = COALESCE(actual_time, 0) + ?
            WHERE id = ?
            ''', (actual_duration, self.task_id))
            conn.commit()
            conn.close()
        
        return actual_duration
    
    def pause(self):
        self.pause_time = datetime.now()
        self._pause_event.set()
        self.update_pomodoro_status('paused')
    
    def resume(self):
        if self.pause_time:
            paused_seconds = (datetime.now() - self.pause_time).total_seconds()
            self.total_paused_seconds += int(paused_seconds)
            self.pause_time = None
        self._pause_event.clear()
        self.update_pomodoro_status('running')
    
    def get_status_text(self):
        if self.status == 'running':
            return Text("🏃 运行中", style="green")
        elif self.status == 'paused':
            return Text("⏸️  已暂停", style="yellow")
        elif self.status == 'completed':
            return Text("✅ 已完成", style="green")
        elif self.status == 'cancelled':
            return Text("❌ 已取消", style="red")
        return Text("⏳ 等待中", style="dim")
    
    def get_progress_info(self):
        elapsed = self.total_seconds - self.remaining_seconds
        progress = elapsed / self.total_seconds * 100 if self.total_seconds > 0 else 0
        return elapsed, self.remaining_seconds, progress


def run_interactive_session(session):
    console.clear()
    
    def display_header():
        header = Panel(
            f"[bold]🍅 番茄钟专注会话[/bold]\n\n"
            f"[cyan]任务:[/cyan] {session.task_title or '无关联任务'}\n"
            f"[cyan]状态:[/cyan] {session.get_status_text()}\n"
            f"[cyan]计划时长:[/cyan] {format_duration(session.duration)}\n"
            f"[cyan]干扰次数:[/cyan] {session.interruptions}",
            title=f"番茄钟 #{session.pomodoro_id}",
            border_style="magenta"
        )
        return header
    
    def display_controls():
        controls = Text()
        controls.append("⌨️  控制命令: ", style="bold")
        controls.append("p", style="yellow")
        controls.append("暂停 ")
        controls.append("r", style="green")
        controls.append("恢复 ")
        controls.append("i", style="cyan")
        controls.append("记录干扰 ")
        controls.append("q", style="red")
        controls.append("提前结束 ")
        controls.append("?", style="dim")
        controls.append("帮助")
        return controls
    
    def display_progress():
        elapsed, remaining, progress = session.get_progress_info()
        bar_length = 40
        filled = int(progress / 100 * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        progress_text = Text()
        progress_text.append(f"{bar} ", style="magenta")
        progress_text.append(f"{progress:5.1f}%  ", style="bold")
        progress_text.append(f"⏱️  剩余: {format_duration(remaining // 60)}", style="cyan")
        return progress_text
    
    def handle_command(cmd):
        cmd = cmd.strip().lower()
        
        if cmd == 'p' and session.status == 'running':
            session.pause()
            session.status = 'paused'
            return True, "已暂停"
            
        elif cmd == 'r' and session.status == 'paused':
            session.resume()
            session.status = 'running'
            return True, "已恢复"
            
        elif cmd == 'i':
            note = click.prompt("请输入干扰原因（直接回车跳过）", default="", show_default=False)
            session.add_interruption(note if note else None)
            return True, f"已记录干扰 #{session.interruptions}"
            
        elif cmd == 'q':
            if click.confirm("确定要提前结束吗？将记录已专注的时间"):
                actual = session.cancel()
                session.status = 'cancelled'
                return False, f"已结束，实际专注 {format_duration(actual)}"
            return True, "继续专注"
            
        elif cmd == '?':
            return True, "\n".join([
                "p      - 暂停当前番茄钟",
                "r      - 恢复暂停的番茄钟",
                "i      - 记录一次干扰",
                "q      - 提前结束，记录已专注时间",
                "?      - 显示此帮助信息",
                "<回车> - 刷新显示"
            ])
            
        elif cmd == '':
            return True, None
            
        else:
            return True, f"未知命令: {cmd}，输入 ? 查看帮助"
    
    layout = Layout()
    layout.split(
        Layout(name="header", size=8),
        Layout(name="progress", size=3),
        Layout(name="controls", size=2),
        Layout(name="messages", size=10)
    )
    
    messages = []
    
    session.status = 'running'
    messages.append(("🍅 番茄钟开始！", "green"))
    
    with Live(layout, refresh_per_second=4, screen=True):
        layout["header"].update(display_header())
        layout["progress"].update(display_progress())
        layout["controls"].update(display_controls())
        layout["messages"].update(Panel("\n".join([f"[{s}] {m}" for m, s in messages[-5:]]), 
                                          title="消息", border_style="dim"))
        
        def timer_thread():
            while not session._stop_event.is_set() and session.remaining_seconds > 0:
                if not session._pause_event.is_set() and session.status == 'running':
                    time.sleep(0.5)
                    session.remaining_seconds -= 0.5
                    if session.remaining_seconds <= 0:
                        session.remaining_seconds = 0
                        break
                else:
                    time.sleep(0.1)
            
            if session.remaining_seconds <= 0 and session.status == 'running':
                session._command = '_complete'
        
        timer = threading.Thread(target=timer_thread, daemon=True)
        timer.start()
        
        input_queue = []
        
        def input_thread():
            while session.status in ('running', 'paused'):
                try:
                    cmd = sys.stdin.readline().strip()
                    if cmd is not None:
                        input_queue.append(cmd)
                except:
                    break
        
        input_t = threading.Thread(target=input_thread, daemon=True)
        input_t.start()
        
        try:
            while session.status in ('running', 'paused'):
                layout["header"].update(display_header())
                layout["progress"].update(display_progress())
                
                if session._command == '_complete':
                    actual = session.complete()
                    session.status = 'completed'
                    messages.append((f"🎉 番茄钟完成！实际专注 {format_duration(actual)}", "green"))
                    break
                
                if input_queue:
                    cmd = input_queue.pop(0)
                    if cmd == '':
                        continue
                        
                    continue_run, msg = handle_command(cmd)
                    if msg:
                        style = "yellow" if "暂停" in msg or "未知" in msg else "cyan"
                        if "已完成" in msg or "已结束" in msg:
                            style = "green"
                        if "已取消" in msg:
                            style = "red"
                        messages.append((msg, style))
                        layout["messages"].update(Panel(
                            "\n".join([f"[{s}] {m}" for m, s in messages[-5:]]), 
                            title="消息", border_style="dim"
                        ))
                    
                    if not continue_run:
                        break
                else:
                    time.sleep(0.1)
                        
        except KeyboardInterrupt:
            session.pause()
            session.status = 'paused'
            messages.append(("检测到中断，已暂停。输入 r 恢复，q 结束", "yellow"))
            layout["messages"].update(Panel(
                "\n".join([f"[{s}] {m}" for m, s in messages[-5:]]), 
                title="消息", border_style="dim"
            ))
                    
        finally:
            session._stop_event.set()
            timer.join(timeout=1)
    
    console.clear()
    
    if session.status == 'completed':
        actual = (session.total_seconds - session.remaining_seconds) // 60
        actual = max(1, actual)
        console.print(Panel(
            f"[bold green]🎉 番茄钟完成！[/bold green]\n\n"
            f"计划时长: {format_duration(session.duration)}\n"
            f"实际专注: {format_duration(actual)}\n"
            f"暂停时间: {format_duration(session.total_paused_seconds // 60)}\n"
            f"干扰次数: {session.interruptions}\n"
            f"任务: {session.task_title or '无关联任务'}",
            title="专注完成", border_style="green"
        ))
        
        short_break = get_config_value('short_break_duration')
        console.print(f"\n☕ 休息 {short_break} 分钟吧！")
        
    elif session.status == 'cancelled':
        actual = (session.total_seconds - session.remaining_seconds) // 60
        console.print(Panel(
            f"[bold yellow]⏹️  番茄钟已提前结束[/bold yellow]\n\n"
            f"已专注: {format_duration(max(1, actual))}\n"
            f"干扰次数: {session.interruptions}\n"
            f"任务: {session.task_title or '无关联任务'}",
            title="提前结束", border_style="yellow"
        ))
    
    return session.status


def start_pomodoro(task_id=None, duration=None):
    session = PomodoroSession(task_id, duration)
    
    if task_id is not None:
        if not session.validate_task():
            console.print(f"[red]✗ 任务 ID {task_id} 不存在，请检查后重试[/red]")
            return None
    
    if not session.create_pomodoro_record():
        console.print("[red]✗ 创建番茄钟记录失败[/red]")
        return None
    
    return run_interactive_session(session)


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


def get_date_range(range_type, start=None, end=None):
    today = date.today()
    
    if range_type == 'today':
        return today, today
    elif range_type == 'week':
        from ..utils import get_week_range
        return get_week_range(today)
    elif range_type == 'month':
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        return start, end
    elif range_type == 'custom' and start and end:
        from ..utils import parse_date
        s = parse_date(start)
        e = parse_date(end)
        if s and e:
            return s, e
    
    return today, today


@click.group()
def focus():
    """番茄钟专注"""
    pass


@focus.command()
@click.option('-t', '--task', 'task_id', type=int, help='关联的任务ID')
@click.option('-d', '--duration', type=int, help='番茄钟时长（分钟）')
def start(task_id, duration):
    """开始番茄钟（交互式会话）"""
    current = get_current_pomodoro()
    if current and current['status'] == 'running':
        console.print(f"[yellow]已有运行中的番茄钟 #{current['id']}[/yellow]")
        console.print("请先结束当前番茄钟，或使用 'focus pause' 暂停")
        return
    
    result = start_pomodoro(task_id, duration)
    return result


@focus.command()
def status():
    """查看当前番茄钟状态"""
    current = get_current_pomodoro()
    
    if not current:
        console.print(Panel(
            "[dim]当前没有进行中的番茄钟[/dim]\n\n"
            "使用 [cyan]eff focus start[/cyan] 开始新的番茄钟",
            title="🍅 番茄钟状态", border_style="dim"
        ))
        return
    
    status_map = {
        'running': '🏃 运行中',
        'paused': '⏸️  暂停中',
        'completed': '✅ 完成',
        'cancelled': '❌ 取消'
    }
    
    start_time = datetime.fromisoformat(current['start_time'])
    elapsed = (datetime.now() - start_time).total_seconds() / 60
    remaining = max(0, current['duration'] - elapsed)
    
    console.print(Panel(
        f"[bold]🍅 当前番茄钟 #{current['id']}[/bold]\n\n"
        f"状态: [cyan]{status_map.get(current['status'], current['status'])}[/cyan]\n"
        f"任务: {current['task_title'] or '无关联任务'}\n"
        f"计划时长: {format_duration(current['duration'])}\n"
        f"已进行: {format_duration(int(elapsed))}\n"
        f"预计剩余: {format_duration(int(remaining))}\n"
        f"干扰次数: {current['interruptions'] or 0}",
        title="番茄钟状态", border_style="cyan"
    ))
    
    if current['interruption_notes']:
        console.print(f"\n[yellow]干扰记录:[/yellow]")
        console.print(current['interruption_notes'])


@focus.command()
@click.option('-r', '--range', 'range_type', 
              type=click.Choice(['today', 'week', 'month', 'custom']), 
              default='today', help='时间范围')
@click.option('-s', '--start', help='自定义开始日期 (YYYY-MM-DD)')
@click.option('-e', '--end', help='自定义结束日期 (YYYY-MM-DD)')
def log(range_type, start, end):
    """查看番茄钟历史"""
    start_date, end_date = get_date_range(range_type, start, end)
    
    pomodoros = get_pomodoros_by_date(start_date, end_date)
    
    if not pomodoros:
        range_label = {
            'today': '今日',
            'week': '本周',
            'month': '本月',
            'custom': f'{format_date(start_date)} 至 {format_date(end_date)}'
        }[range_type]
        
        console.print(Panel(
            f"[dim]{range_label}没有番茄钟记录[/dim]\n\n"
            "使用 [cyan]eff focus start[/cyan] 开始你的第一个番茄钟吧！",
            title="🍅 番茄钟历史", border_style="dim"
        ))
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
    
    range_label = {
        'today': '今日',
        'week': '本周',
        'month': '本月',
        'custom': '自定义'
    }[range_type]
    
    console.print(f"[bold]🍅 {range_label}番茄钟记录[/bold]")
    if range_type == 'custom':
        console.print(f"[dim]{format_date(start_date)} 至 {format_date(end_date)}[/dim]")
    console.print()
    
    console.print(table)
    
    console.print(f"\n📊 统计:")
    console.print(f"  完成番茄钟: {completed_count} 个")
    console.print(f"  总专注时长: {format_duration(total_duration)}")
    
    if range_type == 'today':
        daily_goal = get_config_value('daily_pomodoro_goal')
        if completed_count >= daily_goal:
            console.print(f"  [green]🎯 已达成每日目标 ({daily_goal}个)[/green]")
        else:
            remaining = daily_goal - completed_count
            console.print(f"  [yellow]距每日目标还差 {remaining} 个[/yellow]")
