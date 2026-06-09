import click
from datetime import datetime, date, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..database import get_connection
from ..utils import (
    get_week_range, format_date, format_duration,
    get_priority_label, get_status_label, format_datetime,
    get_date_range, get_range_label
)
from ..config import get_config_value

console = Console()


def get_review_data(start_date, end_date):
    """按日期范围获取复盘数据"""
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


def generate_review_text(review_data, fmt='txt'):
    """生成复盘报告"""
    start = review_data['start_date']
    end = review_data['end_date']
    all_tasks = review_data['all_tasks']
    completed = review_data['completed_tasks']
    pomodoros = review_data['pomodoros']
    notes = review_data['notes']
    
    range_label = f"{format_date(start)} 至 {format_date(end)}"
    
    if fmt == 'markdown':
        lines = []
        lines.append(f"# 复盘报告 - {range_label}")
        lines.append("")
        
        total_focus = sum(p['duration'] for p in pomodoros)
        completion_rate = len(completed) / len(all_tasks) * 100 if all_tasks else 0
        
        lines.append("## 📈 概览统计")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 新增任务 | {len(all_tasks)} 个 |")
        lines.append(f"| 完成任务 | {len(completed)} 个 |")
        lines.append(f"| 完成率 | {completion_rate:.1f}% |")
        lines.append(f"| 番茄钟 | {len(pomodoros)} 个 |")
        lines.append(f"| 专注时长 | {format_duration(total_focus)} |")
        lines.append(f"| 笔记记录 | {len(notes)} 条 |")
        lines.append("")
        
        if completed:
            lines.append("## ✅ 完成的任务")
            lines.append("")
            lines.append("| ID | 标题 | 优先级 | 完成时间 |")
            lines.append("|----|------|--------|----------|")
            for task in completed:
                p_label = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}[task['priority']]
                completed_at = task['completed_at'][:16].replace('T', ' ') if task['completed_at'] else '-'
                lines.append(f"| {task['id']} | {task['title']} | {p_label} | {completed_at} |")
            lines.append("")
        
        if all_tasks:
            lines.append("## 📋 所有任务")
            lines.append("")
            lines.append("| ID | 标题 | 优先级 | 状态 | 创建时间 |")
            lines.append("|----|------|--------|------|----------|")
            for task in all_tasks:
                p_label = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}[task['priority']]
                s_label = {'pending': '⏳ 待办', 'in_progress': '🔄 进行中', 'completed': '✅ 完成', 'cancelled': '❌ 取消'}[task['status']]
                created_at = task['created_at'][:16].replace('T', ' ')
                lines.append(f"| {task['id']} | {task['title']} | {p_label} | {s_label} | {created_at} |")
            lines.append("")
        
        if pomodoros:
            lines.append("## 🍅 专注分布")
            lines.append("")
            task_stats = {}
            for p in pomodoros:
                task_name = p['task_title'] or '无关联任务'
                if task_name not in task_stats:
                    task_stats[task_name] = {'count': 0, 'duration': 0}
                task_stats[task_name]['count'] += 1
                task_stats[task_name]['duration'] += p['duration']
            
            lines.append("| 任务 | 番茄数 | 总时长 |")
            lines.append("|------|--------|--------|")
            for task_name, stats in sorted(task_stats.items(), key=lambda x: -x[1]['duration']):
                lines.append(f"| {task_name} | {stats['count']} | {format_duration(stats['duration'])} |")
            lines.append("")
            
            lines.append("## 📊 番茄钟记录")
            lines.append("")
            lines.append("| ID | 任务 | 时长 | 干扰 | 开始时间 |")
            lines.append("|----|------|------|------|----------|")
            for p in pomodoros:
                task_title = p['task_title'] or '无关联任务'
                start_time = p['start_time'][:16].replace('T', ' ')
                inter = p['interruptions'] or 0
                lines.append(f"| {p['id']} | {task_title} | {format_duration(p['duration'])} | {inter} | {start_time} |")
            lines.append("")
        
        if notes:
            lines.append("## 📝 笔记摘要")
            lines.append("")
            lines.append("| ID | 分类 | 内容摘要 | 创建时间 |")
            lines.append("|----|------|----------|----------|")
            for note in notes[:20]:
                content = note['content'][:50].replace('|', '\\|') + '...' if len(note['content']) > 50 else note['content'].replace('|', '\\|')
                category = note['category'] or '普通'
                created_at = note['created_at'][:16].replace('T', ' ')
                lines.append(f"| {note['id']} | {category} | {content} | {created_at} |")
            lines.append("")
        
        return '\n'.join(lines)
    
    else:
        lines = []
        lines.append(f"📊 复盘报告 - {format_date(start)} 至 {format_date(end)}")
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
            lines.append(f"\n✅ 完成的任务:")
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
            lines.append(f"\n📝 笔记摘要:")
            for note in notes[:10]:
                preview = note['content'][:50] + '...' if len(note['content']) > 50 else note['content']
                category = note['category'] or '普通'
                lines.append(f"  - [{note['id']}] ({category}) {preview}")
        
        return '\n'.join(lines)


def export_report(content, range_type, start_date, end_date, fmt='txt'):
    """导出报告到文件"""
    export_dir = Path(get_config_value('export_dir')).expanduser()
    export_dir.mkdir(parents=True, exist_ok=True)
    
    range_label = {
        'today': 'today',
        'week': 'week',
        'month': 'month',
        'custom': f"{start_date.isoformat()}_{end_date.isoformat()}"
    }.get(range_type, 'custom')
    
    filename = f"review_{range_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    file_path = export_dir / filename
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path


def add_date_range_options(f):
    """添加日期范围选项的装饰器"""
    f = click.option('-r', '--range', 'range_type',
                     type=click.Choice(['today', 'week', 'month', 'custom']),
                     default='week', help='时间范围')(f)
    f = click.option('-w', '--week', 'week_offset', type=int, default=0, help='周偏移，0为本周，-1为上周')(f)
    f = click.option('-s', '--start', help='自定义开始日期 (YYYY-MM-DD)')(f)
    f = click.option('-e', '--end', help='自定义结束日期 (YYYY-MM-DD)')(f)
    return f


def add_export_options(f):
    """添加导出选项的装饰器"""
    f = click.option('--export', 'export_fmt',
                     type=click.Choice(['txt', 'markdown']),
                     help='导出报告格式')(f)
    f = click.option('-o', '--output', help='导出文件名（可选）')(f)
    f = click.option('--open', 'open_file', is_flag=True, help='导出后打开文件')(f)
    return f


def get_review_dates(range_type, week_offset, start, end):
    """获取复盘日期范围"""
    if range_type == 'week' and week_offset != 0:
        today = date.today() + timedelta(weeks=week_offset)
        return get_week_range(today)
    return get_date_range(range_type, start, end)


@click.group()
def review():
    """复盘分析"""
    pass


@review.command()
@add_date_range_options
@add_export_options
def period(range_type, week_offset, start, end, export_fmt, output, open_file):
    """按时间范围复盘"""
    start_date, end_date = get_review_dates(range_type, week_offset, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    review_data = get_review_data(start_date, end_date)
    
    all_tasks = review_data['all_tasks']
    pomodoros = review_data['pomodoros']
    notes = review_data['notes']
    
    if not all_tasks and not pomodoros and not notes:
        console.print(Panel(
            f"[dim]{range_label}没有复盘数据[/dim]\n\n"
            "开始使用 eff 添加任务和番茄钟后，这里会显示复盘信息",
            title=f"📊 {range_label}复盘", border_style="dim"
        ))
        return
    
    review_text = generate_review_text(review_data, fmt='txt')
    console.print(Panel(review_text, title=f"📊 {range_label}复盘", border_style="green"))
    
    if export_fmt:
        report = generate_review_text(review_data, fmt=export_fmt)
        file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")
        
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
@click.option('-w', '--week', type=int, default=0, help='周偏移，0为本周，-1为上周')
@add_export_options
def week(week, export_fmt, output, open_file):
    """按周复盘"""
    start_date, end_date = get_review_dates('week', week, None, None)
    range_label = "本周复盘" if week == 0 else f"{abs(week)}周前复盘"
    
    review_data = get_review_data(start_date, end_date)
    
    all_tasks = review_data['all_tasks']
    pomodoros = review_data['pomodoros']
    notes = review_data['notes']
    
    if not all_tasks and not pomodoros and not notes:
        console.print(Panel(
            f"[dim]{range_label}没有复盘数据[/dim]\n\n"
            "开始使用 eff 添加任务和番茄钟后，这里会显示复盘信息",
            title=f"📊 {range_label}", border_style="dim"
        ))
        return
    
    review_text = generate_review_text(review_data, fmt='txt')
    console.print(Panel(review_text, title=f"📊 {range_label}", border_style="green"))
    
    if export_fmt:
        report = generate_review_text(review_data, fmt=export_fmt)
        file_path = export_report(report, 'week', start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")
        
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
@add_date_range_options
@add_export_options
def export(range_type, week_offset, start, end, export_fmt, output, open_file):
    """导出复盘报告"""
    if export_fmt is None:
        export_fmt = 'txt'
    
    start_date, end_date = get_review_dates(range_type, week_offset, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    review_data = get_review_data(start_date, end_date)
    
    all_tasks = review_data['all_tasks']
    pomodoros = review_data['pomodoros']
    notes = review_data['notes']
    
    if not all_tasks and not pomodoros and not notes:
        console.print(Panel(
            f"[dim]{range_label}没有复盘数据可导出[/dim]",
            title="导出报告", border_style="dim"
        ))
        return
    
    report = generate_review_text(review_data, fmt=export_fmt)
    file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
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
@add_date_range_options
def tasks(range_type, week_offset, start, end):
    """查看任务列表"""
    start_date, end_date = get_review_dates(range_type, week_offset, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    review_data = get_review_data(start_date, end_date)
    tasks = review_data['all_tasks']
    
    if not tasks:
        console.print(Panel(
            f"[dim]{range_label}没有任务[/dim]",
            title=f"📋 {range_label}任务列表", border_style="dim"
        ))
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
    
    console.print(f"[bold]📋 {range_label}任务列表[/bold]\n")
    console.print(table)


@review.command()
@add_date_range_options
def focus(range_type, week_offset, start, end):
    """查看专注记录"""
    start_date, end_date = get_review_dates(range_type, week_offset, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    review_data = get_review_data(start_date, end_date)
    pomodoros = review_data['pomodoros']
    
    if not pomodoros:
        console.print(Panel(
            f"[dim]{range_label}没有专注记录[/dim]\n\n"
            "使用 [cyan]eff focus start[/cyan] 开始番茄钟吧！",
            title=f"🍅 {range_label}专注记录", border_style="dim"
        ))
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
    
    console.print(f"[bold]🍅 {range_label}专注记录[/bold]\n")
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
    
    has_data = any(
        s['tasks'] > 0 or s['completed'] > 0 or s['pomodoros'] > 0
        for s in daily_stats.values()
    )
    
    if not has_data:
        console.print(Panel(
            f"[dim]最近 {days} 天没有数据[/dim]\n\n"
            "开始使用 eff 后这里会显示趋势图",
            title="📈 近期趋势", border_style="dim"
        ))
        return
    
    console.print(f"[bold]📈 最近 {days} 天趋势[/bold]\n")
    
    all_focus = [s['focus'] for s in daily_stats.values()]
    max_focus = max(all_focus) if all_focus else 1
    
    for d, stats in sorted(daily_stats.items()):
        bar = '█' * min(stats['pomodoros'], 10)
        focus_str = format_duration(stats['focus']) if stats['focus'] else '-'
        console.print(f"{format_date(d)} | {bar:<10} | 任务:{stats['tasks']:2d} 完成:{stats['completed']:2d} 🍅:{stats['pomodoros']:2d} ⏱️:{focus_str}")
