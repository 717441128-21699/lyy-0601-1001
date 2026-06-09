import click
import json
import os
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.prompt import Confirm
from rich.progress import Progress, BarColumn, TextColumn

from ..database import get_connection, get_db_path
from ..config import get_config_value, set_config_value
from ..utils import format_datetime

console = Console()


def export_data(export_path=None, include_completed=True):
    if export_path is None:
        export_dir = Path(get_config_value('export_dir')).expanduser()
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"eff_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    conn = get_connection()
    cursor = conn.cursor()
    
    data = {
        'export_time': datetime.now().isoformat(),
        'version': '1.0',
        'tasks': [],
        'pomodoros': [],
        'notes': [],
        'templates': [],
        'plans': []
    }
    
    task_query = 'SELECT * FROM tasks'
    if not include_completed:
        task_query += " WHERE status != 'completed'"
    
    cursor.execute(task_query)
    data['tasks'] = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM pomodoros')
    data['pomodoros'] = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM notes')
    data['notes'] = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM templates')
    data['templates'] = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM plans')
    data['plans'] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return export_path, data


def import_data(import_path, merge=True, overwrite=False):
    if not os.path.exists(import_path):
        raise FileNotFoundError(f"文件不存在: {import_path}")
    
    with open(import_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    stats = {'tasks': 0, 'pomodoros': 0, 'notes': 0, 'templates': 0, 'plans': 0}
    
    if overwrite:
        cursor.execute('DELETE FROM tasks')
        cursor.execute('DELETE FROM pomodoros')
        cursor.execute('DELETE FROM notes')
        cursor.execute('DELETE FROM templates')
        cursor.execute('DELETE FROM plans')
    
    for task in data.get('tasks', []):
        if merge and not overwrite:
            cursor.execute('SELECT id FROM tasks WHERE id = ?', (task['id'],))
            if cursor.fetchone():
                continue
        
        cursor.execute('''
        INSERT OR REPLACE INTO tasks 
        (id, title, description, priority, due_date, tags, status,
         parent_id, estimated_time, actual_time, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task['id'], task['title'], task.get('description'),
            task.get('priority', 1), task.get('due_date'), task.get('tags'),
            task.get('status', 'pending'), task.get('parent_id'),
            task.get('estimated_time'), task.get('actual_time', 0),
            task.get('created_at'), task.get('completed_at')
        ))
        stats['tasks'] += 1
    
    for pomo in data.get('pomodoros', []):
        if merge and not overwrite:
            cursor.execute('SELECT id FROM pomodoros WHERE id = ?', (pomo['id'],))
            if cursor.fetchone():
                continue
        
        cursor.execute('''
        INSERT OR REPLACE INTO pomodoros
        (id, task_id, start_time, end_time, duration, status,
         interruptions, interruption_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pomo['id'], pomo.get('task_id'), pomo['start_time'],
            pomo.get('end_time'), pomo.get('duration', 25),
            pomo.get('status', 'completed'), pomo.get('interruptions', 0),
            pomo.get('interruption_notes')
        ))
        stats['pomodoros'] += 1
    
    for note in data.get('notes', []):
        if merge and not overwrite:
            cursor.execute('SELECT id FROM notes WHERE id = ?', (note['id'],))
            if cursor.fetchone():
                continue
        
        cursor.execute('''
        INSERT OR REPLACE INTO notes
        (id, content, category, tags, template_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            note['id'], note['content'], note.get('category'),
            note.get('tags'), note.get('template_name'),
            note.get('created_at'), note.get('updated_at', note.get('created_at'))
        ))
        stats['notes'] += 1
    
    for template in data.get('templates', []):
        if merge and not overwrite:
            cursor.execute('SELECT id FROM templates WHERE id = ?', (template['id'],))
            if cursor.fetchone():
                continue
        
        try:
            cursor.execute('''
            INSERT OR REPLACE INTO templates
            (id, name, content, created_at)
            VALUES (?, ?, ?, ?)
            ''', (
                template['id'], template['name'], template['content'],
                template.get('created_at')
            ))
            stats['templates'] += 1
        except:
            pass
    
    for plan in data.get('plans', []):
        if merge and not overwrite:
            cursor.execute('SELECT id FROM plans WHERE id = ?', (plan['id'],))
            if cursor.fetchone():
                continue
        
        cursor.execute('''
        INSERT OR REPLACE INTO plans
        (id, plan_date, content, created_at)
        VALUES (?, ?, ?, ?)
        ''', (
            plan['id'], plan['plan_date'], plan.get('content'),
            plan.get('created_at')
        ))
        stats['plans'] += 1
    
    conn.commit()
    conn.close()
    
    return stats


def get_sync_status():
    db_path = get_db_path()
    db_size = os.path.getsize(db_path) / 1024 if os.path.exists(db_path) else 0
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM tasks')
    tasks_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'")
    completed_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM pomodoros')
    pomodoros_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM notes')
    notes_count = cursor.fetchone()[0]
    
    last_sync = get_config_value('last_sync_time')
    
    conn.close()
    
    return {
        'db_size_kb': db_size,
        'tasks': tasks_count,
        'completed': completed_count,
        'pomodoros': pomodoros_count,
        'notes': notes_count,
        'last_sync': last_sync
    }


@click.group()
def sync():
    """数据同步与备份"""
    pass


@sync.command()
@click.option('-o', '--output', 'output_path', help='导出文件路径')
@click.option('--no-completed', is_flag=True, help='不导出已完成的任务')
def export(output_path, no_completed):
    """导出所有数据为 JSON"""
    include_completed = not no_completed
    
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        console=console
    ) as progress:
        task = progress.add_task("导出数据中...", total=100)
        progress.update(task, advance=50)
        
        export_path, data = export_data(output_path, include_completed)
        
        progress.update(task, advance=50)
    
    console.print(f"[green]✓ 数据已导出到: {export_path}[/green]")
    console.print(f"  任务: {len(data['tasks'])} 个")
    console.print(f"  番茄钟: {len(data['pomodoros'])} 个")
    console.print(f"  笔记: {len(data['notes'])} 条")
    console.print(f"  模板: {len(data['templates'])} 个")
    console.print(f"  计划: {len(data['plans'])} 个")


@sync.command('import')
@click.argument('input_path')
@click.option('--merge', is_flag=True, default=True, help='合并数据（默认）')
@click.option('--overwrite', is_flag=True, help='覆盖现有数据')
def import_cmd(input_path, merge, overwrite):
    """从 JSON 文件导入数据"""
    if overwrite:
        if not Confirm.ask("[red]警告: 这将覆盖所有现有数据，确定继续吗？[/red]"):
            return
    
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        console=console
    ) as progress:
        task = progress.add_task("导入数据中...", total=100)
        progress.update(task, advance=30)
        
        stats = import_data(input_path, merge, overwrite)
        
        progress.update(task, advance=70)
    
    console.print(f"[green]✓ 数据导入完成[/green]")
    console.print(f"  任务: {stats['tasks']} 个")
    console.print(f"  番茄钟: {stats['pomodoros']} 个")
    console.print(f"  笔记: {stats['notes']} 条")
    console.print(f"  模板: {stats['templates']} 个")
    console.print(f"  计划: {stats['plans']} 个")
    
    set_config_value('last_sync_time', datetime.now().isoformat())


@sync.command()
def status():
    """查看数据状态"""
    status_data = get_sync_status()
    
    console.print(f"[bold]💾 数据状态[/bold]\n")
    console.print(f"  数据库大小: {status_data['db_size_kb']:.1f} KB")
    console.print(f"  总任务数: {status_data['tasks']}")
    console.print(f"  已完成: {status_data['completed']}")
    console.print(f"  番茄钟: {status_data['pomodoros']}")
    console.print(f"  笔记数: {status_data['notes']}")
    
    if status_data['last_sync']:
        last_sync = datetime.fromisoformat(status_data['last_sync'])
        console.print(f"  上次同步: {format_datetime(last_sync)}")
    else:
        console.print(f"  上次同步: 从未同步")


@sync.command()
@click.option('--path', help='备份文件路径')
def backup(path):
    """创建数据库备份"""
    db_path = get_db_path()
    
    if path is None:
        export_dir = Path(get_config_value('export_dir')).expanduser()
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"eff_db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    
    import shutil
    shutil.copy2(db_path, path)
    
    console.print(f"[green]✓ 数据库已备份到: {path}[/green]")
    
    db_size = os.path.getsize(path) / 1024
    console.print(f"  备份大小: {db_size:.1f} KB")


@sync.command()
def cloud():
    """云同步（需要配置）"""
    sync_config = get_config_value('cloud_sync')
    
    if not sync_config:
        console.print("[yellow]未配置云同步[/yellow]")
        console.print("\n可用的云同步方式:")
        console.print("  1. WebDAV")
        console.print("  2. 自定义脚本")
        console.print("\n使用 'eff config set cloud_sync <type>' 配置")
        return
    
    console.print(f"[cyan]云同步方式: {sync_config}[/cyan]")
    console.print("[yellow]云同步功能正在开发中...[/yellow]")
    console.print("\n当前可以使用 'eff sync export' 和 'eff sync import' 手动同步")
