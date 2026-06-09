import click
from datetime import datetime, date, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..database import get_connection
from ..utils import (
    parse_date, format_date, format_duration,
    get_priority_label, get_status_label
)
from .task import add_task, list_tasks, display_tasks

console = Console()


def generate_daily_plan(plan_date=None):
    if plan_date is None:
        plan_date = date.today()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT * FROM tasks 
    WHERE status != 'completed'
    AND (due_date IS NULL OR due_date <= ?)
    AND parent_id IS NULL
    ORDER BY priority DESC, due_date ASC, created_at ASC
    '''
    
    cursor.execute(query, (plan_date.isoformat(),))
    high_priority = [r for r in cursor.fetchall() if r['priority'] >= 3]
    
    cursor.execute('''
    SELECT * FROM tasks 
    WHERE status != 'completed'
    AND parent_id IS NULL
    ORDER BY priority DESC, due_date ASC, created_at ASC
    LIMIT 10
    ''')
    other_tasks = [r for r in cursor.fetchall() if r['priority'] < 3]
    
    conn.close()
    
    plan = {
        'date': plan_date,
        'must_do': high_priority[:3],
        'should_do': high_priority[3:6],
        'could_do': other_tasks[:4]
    }
    
    return plan


def save_plan(plan_date, content):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR REPLACE INTO plans (plan_date, content)
    VALUES (?, ?)
    ''', (plan_date.isoformat(), content))
    
    conn.commit()
    conn.close()


def get_saved_plan(plan_date):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM plans WHERE plan_date = ?', (plan_date.isoformat(),))
    row = cursor.fetchone()
    conn.close()
    
    return row


def generate_plan_text(plan):
    lines = []
    lines.append(f"📅 今日计划 - {format_date(plan['date'])}")
    lines.append("=" * 40)
    
    if plan['must_do']:
        lines.append("\n🔥 必须完成 (高优先级):")
        for i, task in enumerate(plan['must_do'], 1):
            est = format_duration(task['estimated_time']) if task['estimated_time'] else ''
            lines.append(f"  {i}. [{task['id']}] {task['title']} {est}")
    
    if plan['should_do']:
        lines.append("\n✅ 应该完成:")
        for i, task in enumerate(plan['should_do'], 1):
            est = format_duration(task['estimated_time']) if task['estimated_time'] else ''
            lines.append(f"  {i}. [{task['id']}] {task['title']} {est}")
    
    if plan['could_do']:
        lines.append("\n💪 可以尝试:")
        for i, task in enumerate(plan['could_do'], 1):
            est = format_duration(task['estimated_time']) if task['estimated_time'] else ''
            lines.append(f"  {i}. [{task['id']}] {task['title']} {est}")
    
    total_estimate = sum(
        (t['estimated_time'] or 0) 
        for t in plan['must_do'] + plan['should_do'] + plan['could_do']
    )
    lines.append(f"\n⏱️  预估总耗时: {format_duration(total_estimate)}")
    
    return '\n'.join(lines)


@click.group()
def plan():
    """计划管理"""
    pass


@plan.command()
@click.option('-d', '--date', 'date_str', help='生成计划的日期 (YYYY-MM-DD, today, tomorrow)')
@click.option('-s', '--save', is_flag=True, help='保存生成的计划')
def generate(date_str, save):
    """生成今日计划"""
    plan_date = parse_date(date_str) if date_str else date.today()
    
    plan = generate_daily_plan(plan_date)
    plan_text = generate_plan_text(plan)
    
    console.print(Panel(plan_text, title="今日计划", border_style="cyan"))
    
    if save:
        save_plan(plan_date, plan_text)
        console.print(f"\n[green]✓ 计划已保存[/green]")


@plan.command()
@click.option('-d', '--date', 'date_str', help='查看计划的日期')
def show(date_str):
    """查看已保存的计划"""
    plan_date = parse_date(date_str) if date_str else date.today()
    
    saved = get_saved_plan(plan_date)
    
    if saved:
        console.print(Panel(saved['content'], title=f"计划 - {format_date(plan_date)}", border_style="cyan"))
    else:
        console.print(f"[yellow]没有找到 {format_date(plan_date)} 的计划[/yellow]")


@plan.command()
@click.argument('title')
@click.option('-d', '--description', help='任务描述')
@click.option('-p', '--priority', type=click.IntRange(1, 4), default=3, help='优先级 1-4')
@click.option('-D', '--due', help='截止日期')
@click.option('-t', '--tags', help='标签')
@click.option('-e', '--estimate', type=int, help='预估耗时（分钟）')
@click.option('-s', '--split', 'split_into', type=int, help='自动拆分为N个子任务')
def quickadd(title, description, priority, due, tags, estimate, split_into):
    """快速添加任务到今日计划"""
    task_id = add_task(title, description, priority, due, tags, None, estimate)
    console.print(f"[green]✓ 任务已创建，ID: {task_id}[/green]")
    
    if split_into and split_into > 1:
        subtasks = [f"{title} - 步骤{i}" for i in range(1, split_into + 1)]
        from .task import split_task
        if split_task(task_id, subtasks):
            console.print(f"[green]✓ 已自动拆分为 {split_into} 个子任务[/green]")


@plan.command()
def today():
    """显示今日待办"""
    today_str = date.today().isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT t.*,
           (SELECT COUNT(*) FROM tasks WHERE parent_id = t.id) as subtask_count
    FROM tasks t
    WHERE t.status != 'completed'
    AND (t.due_date IS NULL OR t.due_date <= ?)
    AND t.parent_id IS NULL
    ORDER BY t.priority DESC, t.due_date ASC
    ''', (today_str,))
    
    tasks = cursor.fetchall()
    conn.close()
    
    if not tasks:
        console.print("[green]🎉 今日没有待办任务！[/green]")
    else:
        console.print(f"[bold cyan]📅 今日待办 ({format_date(date.today())})[/bold cyan]\n")
        display_tasks(tasks)


@plan.command()
@click.argument('task_id', type=int)
@click.argument('subtasks', nargs=-1, required=True)
def split(task_id, subtasks):
    """拆分子任务（同 task split）"""
    from .task import split_task
    if split_task(task_id, subtasks):
        console.print(f"[green]✓ 已创建 {len(subtasks)} 个子任务[/green]")
    else:
        console.print(f"[red]✗ 父任务不存在[/red]")


@plan.command()
@click.option('-d', '--date', 'date_str', help='日期')
def checklist(date_str):
    """显示可勾选的任务清单"""
    plan_date = parse_date(date_str) if date_str else date.today()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT t.*,
           (SELECT COUNT(*) FROM tasks WHERE parent_id = t.id) as subtask_count
    FROM tasks t
    WHERE t.parent_id IS NULL
    ORDER BY t.priority DESC, t.due_date ASC
    ''')
    
    tasks = cursor.fetchall()
    conn.close()
    
    console.print(f"[bold]📋 任务清单 - {format_date(plan_date)}[/bold]\n")
    
    for task in tasks:
        checkbox = "[x]" if task['status'] == 'completed' else "[ ]"
        priority = get_priority_label(task['priority'])
        console.print(f"  {checkbox} #{task['id']} {priority} {task['title']}")
