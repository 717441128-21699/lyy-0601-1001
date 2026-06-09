import click
from datetime import datetime, date, timedelta
from collections import defaultdict
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..database import get_connection
from ..utils import (
    format_date, format_duration, format_datetime,
    get_priority_label, get_status_label, is_overdue,
    get_week_range
)
from ..config import get_config_value

console = Console()


def get_time_stats(days=30):
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    stats = {
        'total_tasks': 0,
        'completed_tasks': 0,
        'incomplete_tasks': 0,
        'total_focus': 0,
        'total_pomodoros': 0,
        'avg_focus_per_day': 0,
        'by_priority': defaultdict(lambda: {'total': 0, 'completed': 0}),
        'by_tag': defaultdict(lambda: {'total': 0, 'completed': 0, 'focus': 0}),
        'daily_focus': defaultdict(int)
    }
    
    cursor.execute('''
    SELECT * FROM tasks 
    WHERE DATE(created_at) >= ?
    ''', (start_date.isoformat(),))
    
    tasks = cursor.fetchall()
    stats['total_tasks'] = len(tasks)
    
    for task in tasks:
        stats['by_priority'][task['priority']]['total'] += 1
        if task['status'] == 'completed':
            stats['by_priority'][task['priority']]['completed'] += 1
            stats['completed_tasks'] += 1
        else:
            stats['incomplete_tasks'] += 1
        
        if task['tags']:
            for tag in task['tags'].split(','):
                tag = tag.strip()
                if tag:
                    stats['by_tag'][tag]['total'] += 1
                    if task['status'] == 'completed':
                        stats['by_tag'][tag]['completed'] += 1
                    if task['actual_time']:
                        stats['by_tag'][tag]['focus'] += task['actual_time']
    
    cursor.execute('''
    SELECT DATE(start_time) as d, SUM(duration) as dur, COUNT(*) as cnt
    FROM pomodoros 
    WHERE DATE(start_time) >= ? AND status = 'completed'
    GROUP BY DATE(start_time)
    ''', (start_date.isoformat(),))
    
    for row in cursor.fetchall():
        d = date.fromisoformat(row['d'])
        stats['daily_focus'][d] = row['dur'] or 0
        stats['total_focus'] += row['dur'] or 0
        stats['total_pomodoros'] += row['cnt']
    
    conn.close()
    
    if days > 0:
        stats['avg_focus_per_day'] = stats['total_focus'] / days
    
    return stats


def get_overdue_tasks():
    conn = get_connection()
    cursor = conn.cursor()
    
    today = date.today()
    
    cursor.execute('''
    SELECT t.*,
           (SELECT COUNT(*) FROM tasks WHERE parent_id = t.id) as subtask_count
    FROM tasks t
    WHERE t.status != 'completed'
    AND t.due_date IS NOT NULL
    AND t.due_date < ?
    ORDER BY t.due_date ASC, t.priority DESC
    ''', (today.isoformat(),))
    
    tasks = cursor.fetchall()
    conn.close()
    
    return tasks


def get_efficiency_metrics(days=30):
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT 
        AVG(JULIANDAY(COALESCE(completed_at, CURRENT_TIMESTAMP)) - JULIANDAY(created_at)) * 24 * 60 as avg_completion_time,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
        SUM(estimated_time) as total_estimated,
        SUM(actual_time) as total_actual
    FROM tasks
    WHERE DATE(created_at) >= ?
    ''', (start_date.isoformat(),))
    
    row = cursor.fetchone()
    conn.close()
    
    metrics = {
        'avg_completion_time': row['avg_completion_time'] or 0,
        'completed': row['completed'] or 0,
        'total_estimated': row['total_estimated'] or 0,
        'total_actual': row['total_actual'] or 0
    }
    
    if metrics['total_estimated'] > 0:
        metrics['estimation_accuracy'] = (1 - abs(metrics['total_actual'] - metrics['total_estimated']) / metrics['total_estimated']) * 100
    else:
        metrics['estimation_accuracy'] = 100
    
    return metrics


@click.group()
def stats():
    """统计分析"""
    pass


@stats.command()
@click.option('-d', '--days', type=int, default=30, help='统计天数')
def overview(days):
    """总体统计概览"""
    time_stats = get_time_stats(days)
    metrics = get_efficiency_metrics(days)
    
    console.print(Panel.fit(
        f"[bold]📊 {days} 天统计概览[/bold]\n\n"
        f"📋 任务统计\n"
        f"  新增任务: {time_stats['total_tasks']} 个\n"
        f"  完成任务: {time_stats['completed_tasks']} 个\n"
        f"  完成率: {time_stats['completed_tasks']/time_stats['total_tasks']*100:.1f}%  \n"
        f"  进行中: {time_stats['incomplete_tasks']} 个\n\n"
        f"🍅 专注统计\n"
        f"  番茄钟: {time_stats['total_pomodoros']} 个\n"
        f"  总专注时长: {format_duration(time_stats['total_focus'])}\n"
        f"  日均专注: {format_duration(int(time_stats['avg_focus_per_day']))}\n\n"
        f"📈 效率指标\n"
        f"  平均完成耗时: {format_duration(int(metrics['avg_completion_time']))}\n"
        f"  预估准确度: {metrics['estimation_accuracy']:.1f}%",
        title="统计概览", border_style="blue"
    ))


@stats.command()
def overdue():
    """逾期任务提醒"""
    tasks = get_overdue_tasks()
    
    if not tasks:
        console.print("[green]🎉 没有逾期任务！干得漂亮！[/green]")
        return
    
    console.print(f"[bold red]⚠️  逾期任务提醒 ({len(tasks)} 个)[/bold red]\n")
    
    table = Table(show_header=True, header_style="bold red")
    table.add_column("ID", style="dim", width=6)
    table.add_column("优先级", width=8)
    table.add_column("标题", overflow="fold")
    table.add_column("截止日期", width=15)
    table.add_column("逾期天数", width=10)
    
    today = date.today()
    for task in tasks:
        due_date = datetime.fromisoformat(task['due_date']).date()
        overdue_days = (today - due_date).days
        
        table.add_row(
            str(task['id']),
            get_priority_label(task['priority']),
            task['title'],
            f"[red]{format_date(due_date)}[/red]",
            f"[red]{overdue_days} 天[/red]"
        )
    
    console.print(table)


@stats.command()
@click.option('-d', '--days', type=int, default=30, help='统计天数')
def priority(days):
    """按优先级统计"""
    stats = get_time_stats(days)
    
    console.print(f"[bold]📊 {days} 天优先级分布[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("优先级", width=12)
    table.add_column("总数", width=8)
    table.add_column("已完成", width=10)
    table.add_column("完成率", width=12)
    
    for priority in sorted(stats['by_priority'].keys(), reverse=True):
        data = stats['by_priority'][priority]
        completion_rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
        
        table.add_row(
            get_priority_label(priority),
            str(data['total']),
            str(data['completed']),
            f"{completion_rate:.1f}%"
        )
    
    console.print(table)


@stats.command()
@click.option('-d', '--days', type=int, default=30, help='统计天数')
@click.option('-n', '--limit', type=int, default=10, help='显示标签数量')
def tags(days, limit):
    """按标签统计"""
    stats = get_time_stats(days)
    
    if not stats['by_tag']:
        console.print("[yellow]没有找到标签数据[/yellow]")
        return
    
    console.print(f"[bold]📊 {days} 天标签统计 (Top {limit})[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("标签", width=15)
    table.add_column("任务数", width=8)
    table.add_column("已完成", width=10)
    table.add_column("完成率", width=12)
    table.add_column("专注时长", width=12)
    
    sorted_tags = sorted(
        stats['by_tag'].items(), 
        key=lambda x: x[1]['total'], 
        reverse=True
    )[:limit]
    
    for tag, data in sorted_tags:
        completion_rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
        
        table.add_row(
            tag,
            str(data['total']),
            str(data['completed']),
            f"{completion_rate:.1f}%",
            format_duration(data['focus'])
        )
    
    console.print(table)


@stats.command()
@click.option('-d', '--days', type=int, default=30, help='统计天数')
def time(days):
    """耗时统计"""
    stats = get_time_stats(days)
    
    console.print(f"[bold]⏱️  {days} 天耗时统计[/bold]\n")
    
    if not stats['daily_focus']:
        console.print("[yellow]没有找到专注记录[/yellow]")
        return
    
    weekly_data = defaultdict(lambda: {'focus': 0, 'days': 0})
    for d, focus in stats['daily_focus'].items():
        week_start = d - timedelta(days=d.weekday())
        weekly_data[week_start]['focus'] += focus
        weekly_data[week_start]['days'] += 1
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("周期", width=20)
    table.add_column("总专注", width=12)
    table.add_column("日均专注", width=12)
    table.add_column("活跃度", width=15)
    
    for week_start in sorted(weekly_data.keys(), reverse=True):
        week_end = week_start + timedelta(days=6)
        data = weekly_data[week_start]
        avg_focus = data['focus'] / max(data['days'], 1)
        activity = '█' * min(int(avg_focus / 30), 10)
        
        table.add_row(
            f"{format_date(week_start)} - {format_date(week_end)}",
            format_duration(data['focus']),
            format_duration(int(avg_focus)),
            activity
        )
    
    console.print(table)


@stats.command()
@click.option('-d', '--days', type=int, default=7, help='统计天数')
def daily(days):
    """每日统计"""
    stats = get_time_stats(days)
    
    console.print(f"[bold]📅 最近 {days} 天每日统计[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("日期", width=12)
    table.add_column("专注", width=12)
    table.add_column("番茄钟", width=10)
    table.add_column("趋势", width=20)
    
    max_focus = max(stats['daily_focus'].values()) if stats['daily_focus'] else 1
    
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        focus = stats['daily_focus'].get(d, 0)
        bar_length = int(focus / max_focus * 15) if max_focus > 0 else 0
        bar = '█' * bar_length
        
        table.add_row(
            format_date(d),
            format_duration(focus),
            str(int(focus / 25)) if focus > 0 else '-',
            bar
        )
    
    console.print(table)


@stats.command()
def summary():
    """显示完整统计摘要"""
    today = date.today()
    week_start, week_end = get_week_range()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE status != "completed"')
    pending = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "completed"')
    completed = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE DATE(created_at) = ?', (today.isoformat(),))
    today_added = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE DATE(completed_at) = ?', (today.isoformat(),))
    today_completed = cursor.fetchone()[0]
    
    cursor.execute('SELECT COALESCE(SUM(duration), 0) FROM pomodoros WHERE DATE(start_time) = ? AND status = "completed"', (today.isoformat(),))
    today_focus = cursor.fetchone()[0]
    
    cursor.execute('SELECT COALESCE(SUM(duration), 0) FROM pomodoros WHERE DATE(start_time) BETWEEN ? AND ? AND status = "completed"', (week_start.isoformat(), week_end.isoformat()))
    week_focus = cursor.fetchone()[0]
    
    conn.close()
    
    overdue = get_overdue_tasks()
    daily_goal = get_config_value('daily_pomodoro_goal')
    today_pomodoros = int(today_focus / 25)
    
    console.print(Panel(
        f"[bold]📊 今日摘要[/bold]\n\n"
        f"📋 待办任务: {pending} 个\n"
        f"✅ 已完成: {completed} 个\n"
        f"📝 今日新增: {today_added} 个\n"
        f"🏆 今日完成: {today_completed} 个\n\n"
        f"🍅 今日番茄: {today_pomodoros}/{daily_goal} 个\n"
        f"⏱️  今日专注: {format_duration(today_focus)}\n"
        f"📅 本周专注: {format_duration(week_focus)}\n\n"
        f"[red]⚠️  逾期任务: {len(overdue)} 个[/red]",
        title="效率摘要", border_style="cyan"
    ))
    
    if overdue:
        console.print("\n[yellow]💡 建议: 先处理高优先级的逾期任务[/yellow]")
