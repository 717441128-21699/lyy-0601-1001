import click
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..database import get_connection
from ..utils import (
    parse_date, format_date, format_datetime, format_duration,
    get_priority_label, get_status_label, parse_tags,
    tags_to_str, is_overdue
)
from ..config import get_config_value
from ..search_history import record_search, get_last_search

console = Console()


def add_task(title, description=None, priority=None, due_date=None,
             tags=None, parent_id=None, estimated_time=None):
    if priority is None:
        priority = get_config_value('default_priority')
    
    parsed_due = parse_date(due_date)
    tags_str = tags_to_str(parse_tags(tags))
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO tasks (title, description, priority, due_date, tags,
                       parent_id, estimated_time, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
    ''', (title, description, priority, parsed_due.isoformat() if parsed_due else None,
          tags_str, parent_id, estimated_time))
    
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return task_id


def list_tasks(status=None, priority=None, tag=None, overdue_only=False,
               parent_id=None, limit=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT t.*, 
           (SELECT COUNT(*) FROM tasks WHERE parent_id = t.id) as subtask_count
    FROM tasks t
    WHERE 1=1
    '''
    params = []
    
    if status:
        query += ' AND t.status = ?'
        params.append(status)
    
    if priority:
        query += ' AND t.priority = ?'
        params.append(priority)
    
    if tag:
        query += ' AND t.tags LIKE ?'
        params.append(f'%{tag}%')
    
    if parent_id is not None:
        if parent_id == 0:
            query += ' AND t.parent_id IS NULL'
        else:
            query += ' AND t.parent_id = ?'
            params.append(parent_id)
    
    query += ' ORDER BY t.priority DESC, t.due_date ASC, t.created_at DESC'
    
    if limit:
        query += ' LIMIT ?'
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if overdue_only:
        from datetime import date
        today = date.today()
        rows = [r for r in rows if r['due_date'] and 
                datetime.fromisoformat(r['due_date']).date() < today 
                and r['status'] != 'completed']
    
    return rows


def complete_task(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if not task:
        return False
    
    cursor.execute('''
    UPDATE tasks 
    SET status = 'completed', completed_at = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (task_id,))
    
    conn.commit()
    conn.close()
    return True


def update_task(task_id, **kwargs):
    conn = get_connection()
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if 'title' in kwargs and kwargs['title'] is not None:
        updates.append('title = ?')
        params.append(kwargs['title'])
    
    if 'description' in kwargs and kwargs['description'] is not None:
        updates.append('description = ?')
        params.append(kwargs['description'])
    
    if 'priority' in kwargs and kwargs['priority'] is not None:
        updates.append('priority = ?')
        params.append(kwargs['priority'])
    
    if 'due_date' in kwargs and kwargs['due_date'] is not None:
        parsed = parse_date(kwargs['due_date'])
        updates.append('due_date = ?')
        params.append(parsed.isoformat() if parsed else None)
    
    if 'tags' in kwargs and kwargs['tags'] is not None:
        tags_str = tags_to_str(parse_tags(kwargs['tags']))
        updates.append('tags = ?')
        params.append(tags_str)
    
    if 'status' in kwargs and kwargs['status'] is not None:
        updates.append('status = ?')
        params.append(kwargs['status'])
    
    if 'estimated_time' in kwargs and kwargs['estimated_time'] is not None:
        updates.append('estimated_time = ?')
        params.append(kwargs['estimated_time'])
    
    if not updates:
        conn.close()
        return False
    
    params.append(task_id)
    query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    
    conn.commit()
    conn.close()
    return True


def delete_task(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if not task:
        conn.close()
        return False
    
    cursor.execute('DELETE FROM tasks WHERE parent_id = ?', (task_id,))
    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    
    conn.commit()
    conn.close()
    return True


def split_task(task_id, subtasks):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    parent = cursor.fetchone()
    
    if not parent:
        conn.close()
        return False
    
    for title in subtasks:
        cursor.execute('''
        INSERT INTO tasks (title, priority, due_date, tags, parent_id, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ''', (title, parent['priority'], parent['due_date'], parent['tags'], task_id))
    
    conn.commit()
    conn.close()
    return True


def display_tasks(tasks):
    if not tasks:
        console.print("[yellow]没有找到任务[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("状态", width=10)
    table.add_column("优先级", width=8)
    table.add_column("标题", overflow="fold")
    table.add_column("截止日期", width=12)
    table.add_column("标签", width=15)
    table.add_column("子任务", width=8)
    table.add_column("预估耗时", width=10)
    
    for task in tasks:
        due_date = None
        if task['due_date']:
            due_date = datetime.fromisoformat(task['due_date']).date()
        
        overdue = is_overdue(due_date, task['status'])
        due_str = format_date(due_date)
        if overdue:
            due_str = f"[red]{due_str} (逾期)[/red]"
        
        table.add_row(
            str(task['id']),
            get_status_label(task['status']),
            get_priority_label(task['priority']),
            task['title'],
            due_str,
            task['tags'] or '-',
            str(task['subtask_count']) if task['subtask_count'] > 0 else '-',
            format_duration(task['estimated_time'])
        )
    
    console.print(table)


@click.group()
def task():
    """任务管理"""
    pass


@task.command()
@click.argument('title')
@click.option('-d', '--description', help='任务描述')
@click.option('-p', '--priority', type=click.IntRange(1, 4), help='优先级 1-4 (1=低, 4=紧急)')
@click.option('-D', '--due', help='截止日期 (YYYY-MM-DD, today, tomorrow)')
@click.option('-t', '--tags', help='标签，用逗号分隔')
@click.option('-e', '--estimate', type=int, help='预估耗时（分钟）')
@click.option('--parent', type=int, help='父任务ID')
def add(title, description, priority, due, tags, estimate, parent):
    """新增任务"""
    task_id = add_task(title, description, priority, due, tags, parent, estimate)
    console.print(f"[green]✓ 任务已创建，ID: {task_id}[/green]")


@task.command('list')
@click.option('-s', '--status', type=click.Choice(['pending', 'in_progress', 'completed', 'cancelled']),
              help='按状态过滤')
@click.option('-p', '--priority', type=click.IntRange(1, 4), help='按优先级过滤')
@click.option('-t', '--tag', help='按标签过滤')
@click.option('--overdue', is_flag=True, help='只显示逾期任务')
@click.option('--parent', type=int, help='按父任务ID过滤，0表示顶级任务')
@click.option('-n', '--limit', type=int, help='显示数量限制')
@click.option('-a', '--all', is_flag=True, help='显示所有任务（包括已完成）')
def list_cmd(status, priority, tag, overdue, parent, limit, all):
    """列出任务"""
    if status is None and not all:
        status = 'pending'
    
    tasks = list_tasks(status, priority, tag, overdue, parent, limit)
    display_tasks(tasks)


@task.command()
@click.argument('task_id', type=int)
def done(task_id):
    """完成任务"""
    if complete_task(task_id):
        console.print(f"[green]✓ 任务 {task_id} 已完成[/green]")
    else:
        console.print(f"[red]✗ 任务 {task_id} 不存在[/red]")


@task.command()
@click.argument('task_id', type=int)
@click.option('-t', '--title', help='新标题')
@click.option('-d', '--description', help='新描述')
@click.option('-p', '--priority', type=click.IntRange(1, 4), help='新优先级')
@click.option('-D', '--due', help='新截止日期')
@click.option('-T', '--tags', help='新标签')
@click.option('-s', '--status', type=click.Choice(['pending', 'in_progress', 'completed', 'cancelled']),
              help='新状态')
@click.option('-e', '--estimate', type=int, help='新预估耗时（分钟）')
def edit(task_id, title, description, priority, due, tags, status, estimate):
    """编辑任务"""
    updated = update_task(
        task_id,
        title=title,
        description=description,
        priority=priority,
        due_date=due,
        tags=tags,
        status=status,
        estimated_time=estimate
    )
    
    if updated:
        console.print(f"[green]✓ 任务 {task_id} 已更新[/green]")
    else:
        console.print(f"[yellow]没有更新任何内容[/yellow]")


@task.command()
@click.argument('task_id', type=int)
def delete(task_id):
    """删除任务"""
    if Confirm.ask(f"确定要删除任务 {task_id} 及其所有子任务吗？"):
        if delete_task(task_id):
            console.print(f"[green]✓ 任务 {task_id} 已删除[/green]")
        else:
            console.print(f"[red]✗ 任务 {task_id} 不存在[/red]")


@task.command()
@click.argument('task_id', type=int)
@click.argument('subtasks', nargs=-1, required=True)
def split(task_id, subtasks):
    """拆分子任务"""
    if split_task(task_id, subtasks):
        console.print(f"[green]✓ 已创建 {len(subtasks)} 个子任务[/green]")
    else:
        console.print(f"[red]✗ 父任务不存在[/red]")


@task.command()
@click.argument('keyword')
def search(keyword):
    """搜索任务"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT t.*,
           (SELECT COUNT(*) FROM tasks WHERE parent_id = t.id) as subtask_count
    FROM tasks t
    WHERE t.title LIKE ? OR t.description LIKE ? OR t.tags LIKE ?
    ORDER BY t.priority DESC, t.created_at DESC
    ''', (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
    
    tasks = cursor.fetchall()
    conn.close()
    
    record_search(keyword, 'task', len(tasks))
    
    if not tasks:
        console.print(Panel(
            f"[dim]没有找到包含 '{keyword}' 的任务[/dim]\n\n"
            "试试其他关键词，或使用 [cyan]eff task list[/cyan] 查看所有任务",
            title="🔍 搜索结果", border_style="dim"
        ))
    else:
        console.print(f"[dim]找到 {len(tasks)} 个匹配的任务[/dim]")
        display_tasks(tasks)


@task.command()
@click.option('-r', '--run', is_flag=True, help='直接运行上次搜索')
def last(run):
    """查看或复用上次搜索"""
    last = get_last_search('task')
    
    if not last:
        console.print(Panel(
            "[dim]还没有搜索记录[/dim]\n\n"
            "使用 [cyan]eff task search <关键词>[/cyan] 开始搜索",
            title="🔍 最近搜索", border_style="dim"
        ))
        return
    
    keyword = last['keyword']
    hit_count = last['hit_count']
    searched_at = datetime.fromisoformat(last['created_at'])
    
    console.print(f"[bold]🔍 上次任务搜索[/bold]\n")
    console.print(f"  关键词: [cyan]{keyword}[/cyan]")
    console.print(f"  命中数: {hit_count}")
    console.print(f"  搜索时间: {format_datetime(searched_at)}")
    
    if run:
        console.print(f"\n[cyan]正在重新搜索...[/cyan]\n")
        ctx = click.get_current_context()
        ctx.invoke(search, keyword=keyword)


@task.command()
@click.argument('task_id', type=int)
def show(task_id):
    """显示任务详情"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    
    if not task:
        console.print(f"[red]✗ 任务 {task_id} 不存在[/red]")
        conn.close()
        return
    
    cursor.execute('SELECT * FROM tasks WHERE parent_id = ? ORDER BY created_at', (task_id,))
    subtasks = cursor.fetchall()
    conn.close()
    
    console.print(f"[bold magenta]=== 任务详情 ===[/bold magenta]")
    console.print(f"ID: [bold]{task['id']}[/bold]")
    console.print(f"标题: {task['title']}")
    if task['description']:
        console.print(f"描述: {task['description']}")
    console.print(f"状态: {get_status_label(task['status'])}")
    console.print(f"优先级: {get_priority_label(task['priority'])}")
    
    if task['due_date']:
        due_date = datetime.fromisoformat(task['due_date']).date()
        overdue = is_overdue(due_date, task['status'])
        due_str = format_date(due_date)
        if overdue:
            console.print(f"截止日期: [red]{due_str} (已逾期)[/red]")
        else:
            console.print(f"截止日期: {due_str}")
    
    if task['tags']:
        console.print(f"标签: {task['tags']}")
    
    if task['estimated_time']:
        console.print(f"预估耗时: {format_duration(task['estimated_time'])}")
    
    if task['actual_time']:
        console.print(f"实际耗时: {format_duration(task['actual_time'])}")
    
    console.print(f"创建时间: {format_datetime(datetime.fromisoformat(task['created_at']))}")
    
    if task['completed_at']:
        console.print(f"完成时间: {format_datetime(datetime.fromisoformat(task['completed_at']))}")
    
    if subtasks:
        console.print(f"\n[bold]子任务:[/bold]")
        for st in subtasks:
            console.print(f"  {get_status_label(st['status'])} #{st['id']} {st['title']}")
