import click
from datetime import datetime, date, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..database import get_connection
from ..utils import (
    get_week_range, format_date, format_duration,
    get_priority_label, get_status_label, format_datetime
)
from ..config import get_config_value

console = Console()


def get_week_review(week_offset=0):
    today = date.today() + timedelta(weeks=week_offset)
    start_date, end_date = get_week_range(today)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM tasks 
    WHERE DATE(created_at) BETWEEN ? AND ?
    ORDER BY created_at
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    all_tasks = cursor.fetchall()
    
    cursor.execute('''
    SELECT * FROM tasks 
    WHERE DATE(completed_at) BETWEEN ? AND ?
    ORDER BY completed_at
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    completed_tasks = cursor.fetchall()
    
    cursor.execute('''
    SELECT p.*, t.title as task_title
    FROM pomodoros p
    LEFT JOIN tasks t ON p.task_id = t.id
    WHERE DATE(p.start_time) BETWEEN ? AND ?
    AND p.status = 'completed'
    ORDER BY p.start_time
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    pomodoros = cursor.fetchall()
    
    cursor.execute('''
    SELECT * FROM notes 
    WHERE DATE(created_at) BETWEEN ? AND ?
    ORDER BY created_at
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    notes = cursor.fetchall()
    
    conn.close()
    
    return {
        'start_date': start_date,
        'end_date': end_date,
        'all_tasks': all_tasks,
        'completed_tasks': completed_tasks,
        'pomodoros': pomodoros,
        'notes': notes
    }


def generate_review_text(review_data):
    start = review_data['start_date']
    end = review_data['end_date']
    all_tasks = review_data['all_tasks']
    completed = review_data['completed_tasks']
    pomodoros = review_data['pomodoros']
    notes = review_data['notes']
    
    lines = []
    lines.append(f"📊 周复盘报告 - {format_date(start)} 至 {format_date(end)}")
    lines.append("=" * 50)
    
    total_focus = sum(p['duration'] for p in pomodoros)
    completion_rate = len(completed) / len(all_tasks) * 100 if all_tasks else 0
    
    lines.append(f"\n📈 概览统计")
    lines.append(f"  新增任务: {len(all_tasks)} 个")
    lines.append(f"  完成任务: {len(completed)} 个")
    lines.append(f"  完成率: {completion_rate:.1f}%")
    lines.append(f"  番茄钟: {len(pomodoros)} 个")
    lines.append(f"  专注时长: {format_duration(total_focus)}")
    lines.append(f"  笔记记录: {len(notes)} 条")
    
    if completed:
        lines.append(f"\n✅ 本周完成的任务:")
        for task in completed:
            lines.append(f"  - [{task['id']}] {task['title']}")
    
    if pomodoros:
        task_stats = {}
        for p in pomodoros:
            task_name = p['task_title'] or '无关联任务'
            if task_name not in task_stats:
                task_stats[task_name] = {'count': 0, 'duration': 0}
            task_stats[task_name]['count'] += 1
            task_stats[task_name]['duration'] += p['duration']
        
        lines.append(f"\n🍅 专注分布:")
        for task_name, stats in sorted(task_stats.items(), key=lambda x: -x[1]['duration']):
            lines.append(f"  - {task_name}: {stats['count']}个番茄, {format_duration(stats['duration'])}")
    
    if notes:
        lines.append(f"\n📝 本周笔记摘要:")
        for note in notes[:10]:
            preview = note['content'][:50] + '...' if len(note['content']) > 50 else note['content']
            category = note['category'] or '普通'
            lines.append(f"  - [{note['id']}] ({category}) {preview}")
    
    return '\n'.join(lines)


def export_to_file(content, filename=None):
    export_dir = Path(get_config_value('export_dir')).expanduser()
    export_dir.mkdir(parents=True, exist_ok=True)
    
    if filename is None:
        filename = f"review_{date.today().isoformat()}.txt"
    
    file_path = export_dir / filename
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path


@click.group()
def review():
    """复盘分析"""
    pass


@review.command()
@click.option('-w', '--week', type=int, default=0, help='周偏移，0为本周，-1为上周')
def week(week):
    """按周复盘"""
    review_data = get_week_review(week)
    review_text = generate_review_text(review_data)
    
    title = "本周复盘" if week == 0 else f"{abs(week)}周前复盘"
    console.print(Panel(review_text, title=title, border_style="green"))


@review.command()
@click.option('-w', '--week', type=int, default=0, help='周偏移，0为本周，-1为上周')
@click.option('-o', '--output', help='导出文件名')
@click.option('--open', 'open_file', is_flag=True, help='导出后打开文件')
def export(week, output, open_file):
    """导出周复盘报告"""
    review_data = get_week_review(week)
    review_text = generate_review_text(review_data)
    
    file_path = export_to_file(review_text, output)
    console.print(f"[green]✓ 报告已导出到: {file_path}[/green]")
    
    if open_file:
        import subprocess
        import platform
        try:
            if platform.system() == 'Windows':
                subprocess.run(['notepad', str(file_path)])
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(file_path)])
            else:
                subprocess.run(['xdg-open', str(file_path)])
        except:
            console.print("[yellow]无法自动打开文件，请手动打开[/yellow]")


@review.command()
@click.option('-w', '--week', type=int, default=0, help='周偏移')
def tasks(week):
    """查看本周任务列表"""
    review_data = get_week_review(week)
    tasks = review_data['all_tasks']
    
    if not tasks:
        console.print("[yellow]本周没有任务[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("状态", width=10)
    table.add_column("优先级", width=8)
    table.add_column("标题", overflow="fold")
    table.add_column("创建时间", width=20)
    table.add_column("完成时间", width=20)
    
    for task in tasks:
        completed_at = ''
        if task['completed_at']:
            completed_at = format_datetime(datetime.fromisoformat(task['completed_at']))
        
        table.add_row(
            str(task['id']),
            get_status_label(task['status']),
            get_priority_label(task['priority']),
            task['title'],
            format_datetime(datetime.fromisoformat(task['created_at'])),
            completed_at
        )
    
    console.print(table)


@review.command()
@click.option('-w', '--week', type=int, default=0, help='周偏移')
def focus(week):
    """查看本周专注记录"""
    review_data = get_week_review(week)
    pomodoros = review_data['pomodoros']
    
    if not pomodoros:
        console.print("[yellow]本周没有专注记录[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("任务", overflow="fold")
    table.add_column("时长", width=10)
    table.add_column("干扰", width=8)
    table.add_column("开始时间", width=20)
    
    total_duration = 0
    for pomo in pomodoros:
        total_duration += pomo['duration']
        table.add_row(
            str(pomo['id']),
            pomo['task_title'] or '-',
            format_duration(pomo['duration']),
            str(pomo['interruptions']) if pomo['interruptions'] else '-',
            format_datetime(datetime.fromisoformat(pomo['start_time']))
        )
    
    console.print(table)
    console.print(f"\n📊 总专注时长: [bold]{format_duration(total_duration)}[/bold]")


@review.command()
@click.option('-d', '--days', type=int, default=30, help='查看最近N天的趋势')
def trend(days):
    """查看近期趋势"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    daily_stats = {}
    
    for i in range(days):
        d = start_date + timedelta(days=i)
        daily_stats[d] = {'tasks': 0, 'completed': 0, 'pomodoros': 0, 'focus': 0}
    
    cursor.execute('''
    SELECT DATE(created_at) as d, COUNT(*) as cnt
    FROM tasks 
    WHERE DATE(created_at) >= ?
    GROUP BY DATE(created_at)
    ''', (start_date.isoformat(),))
    
    for row in cursor.fetchall():
        d = date.fromisoformat(row['d'])
        if d in daily_stats:
            daily_stats[d]['tasks'] = row['cnt']
    
    cursor.execute('''
    SELECT DATE(completed_at) as d, COUNT(*) as cnt
    FROM tasks 
    WHERE DATE(completed_at) >= ? AND status = 'completed'
    GROUP BY DATE(completed_at)
    ''', (start_date.isoformat(),))
    
    for row in cursor.fetchall():
        d = date.fromisoformat(row['d'])
        if d in daily_stats:
            daily_stats[d]['completed'] = row['cnt']
    
    cursor.execute('''
    SELECT DATE(start_time) as d, COUNT(*) as cnt, SUM(duration) as dur
    FROM pomodoros 
    WHERE DATE(start_time) >= ? AND status = 'completed'
    GROUP BY DATE(start_time)
    ''', (start_date.isoformat(),))
    
    for row in cursor.fetchall():
        d = date.fromisoformat(row['d'])
        if d in daily_stats:
            daily_stats[d]['pomodoros'] = row['cnt']
            daily_stats[d]['focus'] = row['dur'] or 0
    
    conn.close()
    
    console.print(f"[bold]📈 最近 {days} 天趋势[/bold]\n")
    
    for d, stats in sorted(daily_stats.items()):
        bar = '█' * min(stats['pomodoros'], 10)
        focus_str = format_duration(stats['focus']) if stats['focus'] else '-'
        console.print(f"{format_date(d)} | {bar:<10} | 任务:{stats['tasks']:2d} 完成:{stats['completed']:2d} 🍅:{stats['pomodoros']:2d} ⏱️:{focus_str}")
