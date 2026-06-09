import click
import json
from datetime import datetime, date, timedelta
from collections import defaultdict
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..database import get_connection
from ..utils import (
    format_date, format_duration, format_datetime,
    get_priority_label, get_status_label, is_overdue,
    get_week_range, get_date_range, get_range_label
)
from ..config import get_config_value

console = Console()


def get_time_stats_by_range(start_date, end_date):
    """按日期范围获取统计数据"""
    conn = get_connection()
    cursor = conn.cursor()
    
    stats = {
        'start_date': start_date,
        'end_date': end_date,
        'total_days': (end_date - start_date).days + 1,
        'total_tasks': 0,
        'completed_tasks': 0,
        'incomplete_tasks': 0,
        'total_focus': 0,
        'total_pomodoros': 0,
        'avg_focus_per_day': 0,
        'completion_rate': 0,
        'by_priority': defaultdict(lambda: {'total': 0, 'completed': 0}),
        'by_tag': defaultdict(lambda: {'total': 0, 'completed': 0, 'focus': 0}),
        'daily_focus': defaultdict(int),
        'daily_tasks': defaultdict(lambda: {'created': 0, 'completed': 0}),
        'tasks': [],
        'pomodoros': [],
        'notes': []
    }
    
    cursor.execute('''
    SELECT * FROM tasks 
    WHERE DATE(created_at) BETWEEN ? AND ?
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    tasks = cursor.fetchall()
    stats['tasks'] = tasks
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
        
        created_date = date.fromisoformat(task['created_at'][:10])
        stats['daily_tasks'][created_date]['created'] += 1
        if task['completed_at']:
            completed_date = date.fromisoformat(task['completed_at'][:10])
            stats['daily_tasks'][completed_date]['completed'] += 1
    
    if stats['total_tasks'] > 0:
        stats['completion_rate'] = stats['completed_tasks'] / stats['total_tasks'] * 100
    
    cursor.execute('''
    SELECT DATE(start_time) as d, SUM(duration) as dur, COUNT(*) as cnt
    FROM pomodoros 
    WHERE DATE(start_time) BETWEEN ? AND ? AND status = 'completed'
    GROUP BY DATE(start_time)
    ''', (start_date.isoformat(), end_date.isoformat()))
    
    for row in cursor.fetchall():
        d = date.fromisoformat(row['d'])
        stats['daily_focus'][d] = row['dur'] or 0
        stats['total_focus'] += row['dur'] or 0
        stats['total_pomodoros'] += row['cnt']
    
    cursor.execute('''
    SELECT p.*, t.title as task_title
    FROM pomodoros p
    LEFT JOIN tasks t ON p.task_id = t.id
    WHERE DATE(p.start_time) BETWEEN ? AND ? AND p.status = 'completed'
    ORDER BY p.start_time
    ''', (start_date.isoformat(), end_date.isoformat()))
    stats['pomodoros'] = cursor.fetchall()
    
    cursor.execute('''
    SELECT * FROM notes 
    WHERE DATE(created_at) BETWEEN ? AND ?
    ORDER BY created_at
    ''', (start_date.isoformat(), end_date.isoformat()))
    stats['notes'] = cursor.fetchall()
    
    conn.close()
    
    if stats['total_days'] > 0:
        stats['avg_focus_per_day'] = stats['total_focus'] / stats['total_days']
    
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


def get_efficiency_metrics(start_date, end_date):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT 
        AVG(JULIANDAY(COALESCE(completed_at, CURRENT_TIMESTAMP)) - JULIANDAY(created_at)) * 24 * 60 as avg_completion_time,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
        SUM(estimated_time) as total_estimated,
        SUM(actual_time) as total_actual
    FROM tasks
    WHERE DATE(created_at) BETWEEN ? AND ?
    ''', (start_date.isoformat(), end_date.isoformat()))
    
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


def generate_stats_report(stats, metrics, fmt='txt', include=None, filter_tag=None):
    """生成统计报告
    
    Args:
        stats: 统计数据
        metrics: 效率指标
        fmt: 导出格式 (txt/markdown/json)
        include: 指定导出的数据类型列表，None 表示全部
        filter_tag: 按标签过滤任务和笔记
    """
    def row_get(row, key, default=None):
        try:
            val = row[key]
            return val if val is not None else default
        except (KeyError, IndexError):
            return default
    
    start_date = stats['start_date']
    end_date = stats['end_date']
    range_label = f"{format_date(start_date)} 至 {format_date(end_date)}"
    
    include = include or ['tasks', 'pomodoros', 'notes']
    
    filtered_tasks = stats['tasks']
    filtered_notes = stats['notes']
    
    if filter_tag:
        filtered_tasks = [t for t in stats['tasks'] if t['tags'] and filter_tag in t['tags'].split(',')]
        filtered_notes = [n for n in stats['notes'] if n['tags'] and filter_tag in n['tags'].split(',')]
    
    if fmt == 'json':
        report = {
            'export_time': datetime.now().isoformat(),
            'version': '1.0',
            'meta': {
                'report_type': 'stats_archive',
                'range': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'label': range_label
                },
                'filters': {
                    'include': list(include),
                    'filter_tag': filter_tag
                }
            },
            'overview': {
                'total_tasks': len(filtered_tasks) if 'tasks' in include else 0,
                'completed_tasks': sum(1 for t in filtered_tasks if t['status'] == 'completed') if 'tasks' in include else 0,
                'total_pomodoros': stats['total_pomodoros'] if 'pomodoros' in include else 0,
                'total_focus_minutes': stats['total_focus'] if 'pomodoros' in include else 0,
            },
            'tasks': [],
            'pomodoros': [],
            'notes': []
        }
        
        if 'tasks' in include:
            for task in filtered_tasks:
                report['tasks'].append({
                    'id': task['id'],
                    'title': task['title'],
                    'description': task['description'],
                    'priority': task['priority'],
                    'due_date': task['due_date'],
                    'tags': task['tags'],
                    'status': task['status'],
                    'parent_id': row_get(task, 'parent_id'),
                    'estimated_time': task['estimated_time'],
                    'actual_time': row_get(task, 'actual_time', 0),
                    'created_at': task['created_at'],
                    'completed_at': task['completed_at']
                })
        
        if 'pomodoros' in include:
            for pomo in stats['pomodoros']:
                report['pomodoros'].append({
                    'id': pomo['id'],
                    'task_id': pomo['task_id'],
                    'start_time': pomo['start_time'],
                    'end_time': row_get(pomo, 'end_time'),
                    'duration': pomo['duration'],
                    'status': row_get(pomo, 'status', 'completed'),
                    'interruptions': row_get(pomo, 'interruptions', 0),
                    'interruption_notes': row_get(pomo, 'interruption_notes')
                })
        
        if 'notes' in include:
            for note in filtered_notes:
                report['notes'].append({
                    'id': note['id'],
                    'content': note['content'],
                    'category': row_get(note, 'category'),
                    'tags': row_get(note, 'tags'),
                    'template_name': row_get(note, 'template_name'),
                    'created_at': note['created_at'],
                    'updated_at': row_get(note, 'updated_at', row_get(note, 'created_at'))
                })
        
        return json.dumps(report, ensure_ascii=False, indent=2)
    
    elif fmt == 'markdown':
        lines = []
        lines.append(f"# 统计报告 - {range_label}")
        lines.append("")
        lines.append("## 📈 概览统计")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 新增任务 | {len(filtered_tasks) if 'tasks' in include else 0} 个 |")
        lines.append(f"| 完成任务 | {sum(1 for t in filtered_tasks if t['status'] == 'completed') if 'tasks' in include else 0} 个 |")
        lines.append(f"| 完成率 | {stats['completion_rate']:.1f}% |")
        lines.append(f"| 进行中 | {stats['incomplete_tasks']} 个 |")
        lines.append(f"| 番茄钟 | {stats['total_pomodoros'] if 'pomodoros' in include else 0} 个 |")
        lines.append(f"| 总专注时长 | {format_duration(stats['total_focus'] if 'pomodoros' in include else 0)} |")
        lines.append(f"| 日均专注 | {format_duration(int(stats['avg_focus_per_day'] if 'pomodoros' in include else 0))} |")
        lines.append(f"| 预估准确度 | {metrics['estimation_accuracy']:.1f}% |")
        lines.append("")
        
        if filter_tag:
            lines.append(f"> **过滤标签**: {filter_tag}")
            lines.append("")
        
        if stats['by_priority'] and 'tasks' in include:
            lines.append("## 🎯 按优先级统计")
            lines.append("")
            lines.append("| 优先级 | 总数 | 已完成 | 完成率 |")
            lines.append("|--------|------|--------|--------|")
            for priority in sorted(stats['by_priority'].keys(), reverse=True):
                data = stats['by_priority'][priority]
                rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
                p_label = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}[priority]
                lines.append(f"| {p_label} | {data['total']} | {data['completed']} | {rate:.1f}% |")
            lines.append("")
        
        if stats['by_tag'] and 'tasks' in include:
            lines.append("## 🏷️  按标签统计")
            lines.append("")
            lines.append("| 标签 | 任务数 | 已完成 | 完成率 | 专注时长 |")
            lines.append("|------|--------|--------|--------|----------|")
            for tag, data in sorted(stats['by_tag'].items(), key=lambda x: -x[1]['total']):
                rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
                lines.append(f"| {tag} | {data['total']} | {data['completed']} | {rate:.1f}% | {format_duration(data['focus'])} |")
            lines.append("")
        
        if filtered_tasks and 'tasks' in include:
            lines.append("## 📋 任务列表")
            lines.append("")
            lines.append("| ID | 标题 | 优先级 | 状态 | 创建时间 | 完成时间 |")
            lines.append("|----|------|--------|------|----------|----------|")
            for task in filtered_tasks:
                p_label = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}[task['priority']]
                s_label = {'pending': '⏳ 待办', 'in_progress': '🔄 进行中', 'completed': '✅ 完成', 'cancelled': '❌ 取消'}[task['status']]
                created_at = task['created_at'][:16].replace('T', ' ')
                completed_at = task['completed_at'][:16].replace('T', ' ') if task['completed_at'] else '-'
                lines.append(f"| {task['id']} | {task['title']} | {p_label} | {s_label} | {created_at} | {completed_at} |")
            lines.append("")
        
        if stats['pomodoros'] and 'pomodoros' in include:
            lines.append("## 🍅 番茄钟记录")
            lines.append("")
            lines.append("| ID | 任务 | 时长 | 干扰次数 | 开始时间 |")
            lines.append("|----|------|------|----------|----------|")
            for pomo in stats['pomodoros']:
                task_title = row_get(pomo, 'task_title') or '无关联任务'
                start_time = pomo['start_time'][:16].replace('T', ' ')
                inter = pomo['interruptions'] or 0
                duration = format_duration(pomo['duration'])
                lines.append(f"| {pomo['id']} | {task_title} | {duration} | {inter} | {start_time} |")
            lines.append("")
        
        if filtered_notes and 'notes' in include:
            lines.append("## 📝 笔记摘要")
            lines.append("")
            lines.append("| ID | 分类 | 内容摘要 | 创建时间 |")
            lines.append("|----|------|----------|----------|")
            for note in filtered_notes:
                content = note['content'][:50].replace('|', '\\|') + '...' if len(note['content']) > 50 else note['content'].replace('|', '\\|')
                category = note['category'] or '普通'
                created_at = note['created_at'][:16].replace('T', ' ')
                lines.append(f"| {note['id']} | {category} | {content} | {created_at} |")
            lines.append("")
        
        return '\n'.join(lines)
    
    else:
        lines = []
        lines.append(f"=== 统计报告 - {range_label} ===")
        lines.append("")
        lines.append("📈 概览统计")
        lines.append(f"  新增任务: {len(filtered_tasks) if 'tasks' in include else 0} 个")
        lines.append(f"  完成任务: {sum(1 for t in filtered_tasks if t['status'] == 'completed') if 'tasks' in include else 0} 个")
        lines.append(f"  完成率: {stats['completion_rate']:.1f}%")
        lines.append(f"  进行中: {stats['incomplete_tasks']} 个")
        lines.append(f"  番茄钟: {stats['total_pomodoros'] if 'pomodoros' in include else 0} 个")
        lines.append(f"  总专注时长: {format_duration(stats['total_focus'] if 'pomodoros' in include else 0)}")
        lines.append(f"  日均专注: {format_duration(int(stats['avg_focus_per_day'] if 'pomodoros' in include else 0))}")
        lines.append(f"  预估准确度: {metrics['estimation_accuracy']:.1f}%")
        lines.append("")
        
        if filter_tag:
            lines.append(f"🔍 过滤标签: {filter_tag}")
            lines.append("")
        
        if stats['by_priority'] and 'tasks' in include:
            lines.append("🎯 按优先级统计")
            for priority in sorted(stats['by_priority'].keys(), reverse=True):
                data = stats['by_priority'][priority]
                rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
                p_label = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}[priority]
                lines.append(f"  {p_label}: {data['total']}个任务, {data['completed']}个完成, 完成率{rate:.1f}%")
            lines.append("")
        
        if stats['by_tag'] and 'tasks' in include:
            lines.append("🏷️  按标签统计 (Top 10)")
            for tag, data in sorted(stats['by_tag'].items(), key=lambda x: -x[1]['total'])[:10]:
                rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
                lines.append(f"  {tag}: {data['total']}个任务, {format_duration(data['focus'])}专注, 完成率{rate:.1f}%")
            lines.append("")
        
        if filtered_tasks and 'tasks' in include:
            lines.append("📋 任务列表")
            lines.append(f"  {'ID':<5} {'状态':<8} {'优先级':<6} {'标题'}")
            lines.append(f"  {'-'*5} {'-'*8} {'-'*6} {'-'*40}")
            for task in filtered_tasks:
                p_label = {4: '🔴', 3: '🟠', 2: '🟡', 1: '🟢'}[task['priority']]
                s_label = {'pending': '待办', 'in_progress': '进行中', 'completed': '完成', 'cancelled': '取消'}[task['status']]
                title = task['title'][:40] + '...' if len(task['title']) > 40 else task['title']
                lines.append(f"  {task['id']:<5} {s_label:<8} {p_label:<6} {title}")
            lines.append("")
        
        if stats['pomodoros'] and 'pomodoros' in include:
            lines.append("🍅 番茄钟记录")
            lines.append(f"  {'ID':<5} {'时长':<8} {'干扰次数':<10} {'开始时间':<20} {'任务'}")
            lines.append(f"  {'-'*5} {'-'*8} {'-'*10} {'-'*20} {'-'*30}")
            for pomo in stats['pomodoros']:
                task_title = row_get(pomo, 'task_title') or '无关联任务'
                task_title = task_title[:30] + '...' if len(task_title) > 30 else task_title
                inter = pomo['interruptions'] or 0
                start_time = pomo['start_time'][:16].replace('T', ' ')
                duration = format_duration(pomo['duration'])
                lines.append(f"  {pomo['id']:<5} {duration:<8} {inter:<10} {start_time:<20} {task_title}")
            lines.append("")
        
        if filtered_notes and 'notes' in include:
            lines.append("📝 笔记摘要")
            lines.append(f"  {'ID':<5} {'分类':<8} {'内容摘要'}")
            lines.append(f"  {'-'*5} {'-'*8} {'-'*50}")
            for note in filtered_notes:
                category = note['category'] or '普通'
                content = note['content'][:50] + '...' if len(note['content']) > 50 else note['content']
                content = content.replace('\n', ' ')
                lines.append(f"  {note['id']:<5} {category:<8} {content}")
            lines.append("")
        
        return '\n'.join(lines)


def export_report(content, range_type, start_date, end_date, fmt='txt'):
    """导出报告到文件"""
    export_dir = Path(get_config_value('export_dir')).expanduser()
    export_dir.mkdir(parents=True, exist_ok=True)
    
    ext = fmt
    range_label = {
        'today': 'today',
        'week': 'week',
        'month': 'month',
        'custom': f"{start_date.isoformat()}_{end_date.isoformat()}"
    }.get(range_type, 'custom')
    
    filename = f"stats_{range_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    file_path = export_dir / filename
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path


def add_date_range_options(f):
    """添加日期范围选项的装饰器"""
    f = click.option('-r', '--range', 'range_type',
                     type=click.Choice(['today', 'week', 'month', 'custom']),
                     default='month', help='时间范围')(f)
    f = click.option('-s', '--start', help='自定义开始日期 (YYYY-MM-DD)')(f)
    f = click.option('-e', '--end', help='自定义结束日期 (YYYY-MM-DD)')(f)
    return f


def add_export_options(f):
    """添加导出选项的装饰器"""
    f = click.option('--export', 'export_fmt',
                     type=click.Choice(['txt', 'markdown', 'json']),
                     help='导出报告格式')(f)
    f = click.option('-o', '--output', help='导出文件名（可选）')(f)
    f = click.option('--include', multiple=True,
                     type=click.Choice(['tasks', 'pomodoros', 'notes']),
                     help='指定导出的数据类型（可多选），默认全部导出')(f)
    f = click.option('--filter-tag', help='按标签过滤任务和笔记')(f)
    return f


@click.group()
def stats():
    """统计分析"""
    pass


@stats.command()
@add_date_range_options
@add_export_options
def overview(range_type, start, end, export_fmt, output, include, filter_tag):
    """总体统计概览"""
    start_date, end_date = get_date_range(range_type, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    metrics = get_efficiency_metrics(start_date, end_date)
    
    has_data = (time_stats['total_tasks'] > 0 or 
                time_stats['total_pomodoros'] > 0 or 
                len(time_stats['notes']) > 0)
    
    if not has_data and not export_fmt:
        console.print(Panel(
            f"[dim]{range_label}没有统计数据[/dim]\n\n"
            "开始使用 eff 添加任务和番茄钟后，这里会显示统计信息",
            title=f"📊 {range_label}统计概览", border_style="dim"
        ))
        return
    
    if has_data:
        console.print(Panel.fit(
            f"[bold]📊 {range_label}统计概览[/bold]\n\n"
            f"📋 任务统计\n"
            f"  新增任务: {time_stats['total_tasks']} 个\n"
            f"  完成任务: {time_stats['completed_tasks']} 个\n"
            f"  完成率: {time_stats['completion_rate']:.1f}%  \n"
            f"  进行中: {time_stats['incomplete_tasks']} 个\n\n"
            f"🍅 专注统计\n"
            f"  番茄钟: {time_stats['total_pomodoros']} 个\n"
            f"  总专注时长: {format_duration(time_stats['total_focus'])}\n"
            f"  日均专注: {format_duration(int(time_stats['avg_focus_per_day']))}\n\n"
            f"📈 效率指标\n"
            f"  平均完成耗时: {format_duration(int(metrics['avg_completion_time']))}\n"
            f"  预估准确度: {metrics['estimation_accuracy']:.1f}%",
            title=f"📊 {range_label}统计", border_style="blue"
        ))
    elif export_fmt:
        console.print(f"[dim]📊 {range_label}没有数据，但将生成空报告用于归档[/dim]")
    
    if export_fmt:
        include_list = list(include) if include else None
        report = generate_stats_report(time_stats, metrics, fmt=export_fmt, 
                                       include=include_list, filter_tag=filter_tag)
        file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")


@stats.command()
@click.option('-p', '--period', 
              type=click.Choice(['week', 'month']), 
              default='week', help='归档周期：week(周) / month(月)')
@click.option('--include', multiple=True,
              type=click.Choice(['tasks', 'pomodoros', 'notes']),
              help='指定归档的数据类型（可多选），默认全部')
@click.option('--filter-tag', help='按标签过滤')
def archive(period, include, filter_tag):
    """按周/月生成归档报告（txt + markdown + json + 索引）"""
    from ..utils import get_week_range, get_month_range
    
    today = date.today()
    if period == 'week':
        start_date, end_date = get_week_range(today)
        range_label = f"{format_date(start_date)}_to_{format_date(end_date)}"
        period_label = "本周"
    else:
        start_date, end_date = get_month_range(today)
        range_label = f"{today.year}_{today.month:02d}"
        period_label = "本月"
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    metrics = get_efficiency_metrics(start_date, end_date)
    
    include_list = list(include) if include else None
    
    export_dir = Path(get_config_value('export_dir')).expanduser()
    archive_dir = export_dir / f"archive_{period}_{range_label}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    formats = ['txt', 'markdown', 'json']
    exported_files = []
    
    for fmt in formats:
        report = generate_stats_report(time_stats, metrics, fmt=fmt,
                                       include=include_list, filter_tag=filter_tag)
        ext = fmt
        filename = f"stats_{period}_{range_label}.{ext}"
        file_path = archive_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(report)
        exported_files.append((fmt, file_path))
    
    index_content = []
    index_content.append(f"# 统计归档 - {period_label}")
    index_content.append("")
    index_content.append(f"**时间范围**: {format_date(start_date)} 至 {format_date(end_date)}")
    index_content.append(f"**生成时间**: {format_datetime(datetime.now())}")
    index_content.append("")
    
    if include_list:
        index_content.append(f"**数据类型**: {', '.join(include_list)}")
    else:
        index_content.append("**数据类型**: 全部")
    
    if filter_tag:
        index_content.append(f"**标签过滤**: {filter_tag}")
    
    index_content.append("")
    index_content.append("## 📁 归档文件")
    index_content.append("")
    index_content.append("| 格式 | 文件名 | 大小 |")
    index_content.append("|------|--------|------|")
    
    total_size = 0
    for fmt, file_path in exported_files:
        size = file_path.stat().st_size
        total_size += size
        index_content.append(f"| {fmt.upper()} | {file_path.name} | {size} B |")
    
    index_content.append("")
    index_content.append(f"**总大小**: {total_size} B")
    index_content.append("")
    index_content.append("## 📊 概览统计")
    index_content.append("")
    index_content.append(f"- 任务数: {time_stats['total_tasks']}")
    index_content.append(f"- 完成数: {time_stats['completed_tasks']}")
    index_content.append(f"- 番茄钟: {time_stats['total_pomodoros']}")
    index_content.append(f"- 总专注: {format_duration(time_stats['total_focus'])}")
    index_content.append(f"- 笔记数: {len(time_stats['notes'])}")
    
    index_path = archive_dir / "README.md"
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(index_content))
    
    console.print(f"[bold green]✓ 归档完成[/bold green]\n")
    console.print(f"[bold]📁 归档目录:[/bold] {archive_dir}")
    console.print(f"[bold]📅 时间范围:[/bold] {format_date(start_date)} 至 {format_date(end_date)}")
    console.print("")
    console.print(f"[bold]📄 包含文件:[/bold]")
    for fmt, file_path in exported_files:
        size = file_path.stat().st_size
        console.print(f"  • {fmt.upper():<10} {file_path.name:<40} ({size} B)")
    console.print(f"  • {'INDEX':<10} README.md")
    console.print("")
    console.print(f"[bold]📊 归档内容:[/bold]")
    console.print(f"  • 任务: {time_stats['total_tasks']} 个 (完成: {time_stats['completed_tasks']} 个)")
    console.print(f"  • 番茄钟: {time_stats['total_pomodoros']} 个 ({format_duration(time_stats['total_focus'])})")
    console.print(f"  • 笔记: {len(time_stats['notes'])} 条")
    
    return archive_dir


@stats.command()
@click.argument('file_path', type=click.Path(exists=True))
def validate(file_path):
    """校验 JSON 导出文件结构，确保能被 sync import 读取"""
    import json
    from pathlib import Path
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗ JSON 解析失败: {e}[/red]")
        return
    except Exception as e:
        console.print(f"[red]✗ 读取文件失败: {e}[/red]")
        return
    
    errors = []
    warnings = []
    
    required_sections = ['tasks', 'pomodoros', 'notes']
    for section in required_sections:
        if section not in data:
            warnings.append(f"缺少可选字段 '{section}'，将视为空列表")
    
    task_required_fields = ['id', 'title']
    task_optional_fields = ['description', 'priority', 'due_date', 'tags', 'status', 
                             'parent_id', 'estimated_time', 'actual_time', 'created_at', 'completed_at']
    
    pomo_required_fields = ['id', 'start_time', 'duration']
    pomo_optional_fields = ['task_id', 'end_time', 'status', 'interruptions', 'interruption_notes']
    
    note_required_fields = ['id', 'content']
    note_optional_fields = ['category', 'tags', 'template_name', 'created_at', 'updated_at']
    
    def validate_items(items, required_fields, optional_fields, item_name):
        item_errors = []
        for i, item in enumerate(items):
            for field in required_fields:
                if field not in item:
                    item_errors.append(f"  {item_name}[{i}] 缺少必填字段: {field}")
            
            for key in item:
                if key not in required_fields and key not in optional_fields:
                    warnings.append(f"  {item_name}[{i}] 包含未知字段: {key}")
        
        return item_errors
    
    if 'tasks' in data:
        if not isinstance(data['tasks'], list):
            errors.append("'tasks' 必须是列表")
        else:
            errors.extend(validate_items(data['tasks'], task_required_fields, task_optional_fields, 'tasks'))
            console.print(f"  📋 任务: {len(data['tasks'])} 条")
    
    if 'pomodoros' in data:
        if not isinstance(data['pomodoros'], list):
            errors.append("'pomodoros' 必须是列表")
        else:
            errors.extend(validate_items(data['pomodoros'], pomo_required_fields, pomo_optional_fields, 'pomodoros'))
            console.print(f"  🍅 番茄钟: {len(data['pomodoros'])} 条")
    
    if 'notes' in data:
        if not isinstance(data['notes'], list):
            errors.append("'notes' 必须是列表")
        else:
            errors.extend(validate_items(data['notes'], note_required_fields, note_optional_fields, 'notes'))
            console.print(f"  📝 笔记: {len(data['notes'])} 条")
    
    if 'meta' in data:
        console.print(f"  📄 元数据: 存在")
        if 'range' in data['meta']:
            console.print(f"    时间范围: {data['meta']['range']}")
    
    console.print()
    
    if warnings:
        console.print(f"[yellow]⚠️  警告 ({len(warnings)} 条):[/yellow]")
        for w in warnings:
            console.print(f"  {w}")
        console.print()
    
    if errors:
        console.print(f"[red]✗ 校验失败 ({len(errors)} 个错误):[/red]")
        for e in errors:
            console.print(f"  {e}")
        console.print(f"\n[red]此文件无法被 sync import 正确读取[/red]")
    else:
        console.print(f"[green]✓ 校验通过！此文件可以被 sync import 正确读取[/green]")
        console.print(f"\n[dim]使用 [cyan]eff sync import {file_path}[/cyan] 导入数据[/dim]")


@stats.command()
def overdue():
    """逾期任务提醒"""
    tasks = get_overdue_tasks()
    
    if not tasks:
        console.print(Panel(
            "[dim]没有逾期任务[/dim]\n\n"
            "[green]🎉 干得漂亮！继续保持[/green]",
            title="⚠️  逾期任务提醒", border_style="green"
        ))
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
@add_date_range_options
@add_export_options
def priority(range_type, start, end, export_fmt, output):
    """按优先级统计"""
    start_date, end_date = get_date_range(range_type, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    
    if not time_stats['by_priority']:
        console.print(Panel(
            f"[dim]{range_label}没有优先级统计数据[/dim]",
            title=f"🎯 {range_label}优先级分布", border_style="dim"
        ))
        return
    
    console.print(f"[bold]📊 {range_label}优先级分布[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("优先级", width=12)
    table.add_column("总数", width=8)
    table.add_column("已完成", width=10)
    table.add_column("完成率", width=12)
    
    for priority in sorted(time_stats['by_priority'].keys(), reverse=True):
        data = time_stats['by_priority'][priority]
        completion_rate = data['completed'] / data['total'] * 100 if data['total'] > 0 else 0
        
        table.add_row(
            get_priority_label(priority),
            str(data['total']),
            str(data['completed']),
            f"{completion_rate:.1f}%"
        )
    
    console.print(table)
    
    if export_fmt:
        metrics = get_efficiency_metrics(start_date, end_date)
        report = generate_stats_report(time_stats, metrics, fmt=export_fmt)
        file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")


@stats.command()
@add_date_range_options
@click.option('-n', '--limit', type=int, default=10, help='显示标签数量')
@add_export_options
def tags(range_type, start, end, limit, export_fmt, output):
    """按标签统计"""
    start_date, end_date = get_date_range(range_type, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    
    if not time_stats['by_tag']:
        console.print(Panel(
            f"[dim]{range_label}没有标签统计数据[/dim]\n\n"
            "给任务添加标签后，这里会显示标签统计",
            title=f"🏷️  {range_label}标签统计", border_style="dim"
        ))
        return
    
    console.print(f"[bold]📊 {range_label}标签统计 (Top {limit})[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("标签", width=15)
    table.add_column("任务数", width=8)
    table.add_column("已完成", width=10)
    table.add_column("完成率", width=12)
    table.add_column("专注时长", width=12)
    
    sorted_tags = sorted(
        time_stats['by_tag'].items(), 
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
    
    if export_fmt:
        metrics = get_efficiency_metrics(start_date, end_date)
        report = generate_stats_report(time_stats, metrics, fmt=export_fmt)
        file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")


@stats.command()
@add_date_range_options
@add_export_options
def time(range_type, start, end, export_fmt, output):
    """耗时统计"""
    start_date, end_date = get_date_range(range_type, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    
    if not time_stats['daily_focus']:
        console.print(Panel(
            f"[dim]{range_label}没有专注记录[/dim]\n\n"
            "使用 [cyan]eff focus start[/cyan] 开始番茄钟吧！",
            title=f"⏱️  {range_label}耗时统计", border_style="dim"
        ))
        return
    
    console.print(f"[bold]⏱️  {range_label}耗时统计[/bold]\n")
    
    weekly_data = defaultdict(lambda: {'focus': 0, 'days': set()})
    for d, focus in time_stats['daily_focus'].items():
        week_start = d - timedelta(days=d.weekday())
        weekly_data[week_start]['focus'] += focus
        weekly_data[week_start]['days'].add(d)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("周期", width=20)
    table.add_column("总专注", width=12)
    table.add_column("日均专注", width=12)
    table.add_column("活跃度", width=15)
    
    all_focus = time_stats['daily_focus'].values()
    max_focus = max(all_focus) if all_focus else 1
    
    for week_start in sorted(weekly_data.keys(), reverse=True):
        week_end = week_start + timedelta(days=6)
        data = weekly_data[week_start]
        days_count = len(data['days'])
        avg_focus = data['focus'] / max(days_count, 1)
        activity = '█' * min(int(avg_focus / 30), 10)
        
        table.add_row(
            f"{format_date(week_start)} - {format_date(week_end)}",
            format_duration(data['focus']),
            format_duration(int(avg_focus)),
            activity
        )
    
    console.print(table)
    
    if export_fmt:
        metrics = get_efficiency_metrics(start_date, end_date)
        report = generate_stats_report(time_stats, metrics, fmt=export_fmt)
        file_path = export_report(report, range_type, start_date, end_date, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")


@stats.command()
@add_date_range_options
def daily(range_type, start, end):
    """每日统计"""
    start_date, end_date = get_date_range(range_type, start, end)
    range_label = get_range_label(range_type, start_date, end_date)
    
    time_stats = get_time_stats_by_range(start_date, end_date)
    
    if not time_stats['daily_focus'] and not time_stats['daily_tasks']:
        console.print(Panel(
            f"[dim]{range_label}没有每日统计数据[/dim]",
            title=f"📅 {range_label}每日统计", border_style="dim"
        ))
        return
    
    console.print(f"[bold]📅 {range_label}每日统计[/bold]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("日期", width=12)
    table.add_column("新增任务", width=10)
    table.add_column("完成任务", width=10)
    table.add_column("专注", width=12)
    table.add_column("番茄钟", width=10)
    table.add_column("趋势", width=20)
    
    all_focus = time_stats['daily_focus'].values()
    max_focus = max(all_focus) if all_focus else 1
    
    days_count = (end_date - start_date).days + 1
    for i in range(days_count):
        d = start_date + timedelta(days=i)
        focus = time_stats['daily_focus'].get(d, 0)
        created = time_stats['daily_tasks'].get(d, {}).get('created', 0)
        completed = time_stats['daily_tasks'].get(d, {}).get('completed', 0)
        pomodoros = int(focus / 25) if focus > 0 else 0
        bar_length = int(focus / max_focus * 15) if max_focus > 0 else 0
        bar = '█' * bar_length + '░' * (15 - bar_length)
        
        table.add_row(
            format_date(d),
            str(created),
            str(completed),
            format_duration(focus),
            str(pomodoros) if pomodoros > 0 else '-',
            bar
        )
    
    console.print(table)


@stats.command()
@add_export_options
def summary(export_fmt, output):
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
    
    if pending == 0 and completed == 0 and today_focus == 0:
        console.print(Panel(
            "[dim]还没有任何数据[/dim]\n\n"
            "开始使用 eff 来管理你的任务和时间吧！\n"
            "  [cyan]eff task add <标题>[/cyan] - 添加任务\n"
            "  [cyan]eff focus start[/cyan] - 开始番茄钟",
            title="📊 效率摘要", border_style="dim"
        ))
        return
    
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
    
    if export_fmt:
        time_stats = get_time_stats_by_range(week_start, week_end)
        metrics = get_efficiency_metrics(week_start, week_end)
        report = generate_stats_report(time_stats, metrics, fmt=export_fmt)
        file_path = export_report(report, 'week', week_start, week_end, fmt=export_fmt)
        console.print(f"\n[green]✓ 报告已导出到: {file_path}[/green]")
