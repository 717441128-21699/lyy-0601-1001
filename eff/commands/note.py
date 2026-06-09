import click
import sqlite3
from datetime import datetime, date
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..database import get_connection
from ..utils import format_datetime, parse_tags, tags_to_str
from ..search_history import record_search, get_last_search

console = Console()


def add_note(content, category=None, tags=None, template_name=None):
    tags_str = tags_to_str(parse_tags(tags))
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO notes (content, category, tags, template_name)
    VALUES (?, ?, ?, ?)
    ''', (content, category, tags_str, template_name))
    
    note_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return note_id


def list_notes(category=None, tag=None, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM notes WHERE 1=1'
    params = []
    
    if category:
        query += ' AND category = ?'
        params.append(category)
    
    if tag:
        query += ' AND tags LIKE ?'
        params.append(f'%{tag}%')
    
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def search_notes(keyword, tag=None, category=None, start_date=None, end_date=None):
    """搜索笔记（支持高级筛选）"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM notes WHERE 1=1'
    params = []
    
    if keyword:
        query += ' AND (content LIKE ? OR category LIKE ? OR tags LIKE ?)'
        params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
    
    if tag:
        query += ' AND tags LIKE ?'
        params.append(f'%{tag}%')
    
    if category:
        query += ' AND category = ?'
        params.append(category)
    
    if start_date:
        query += ' AND DATE(created_at) >= ?'
        params.append(start_date.isoformat())
    
    if end_date:
        query += ' AND DATE(created_at) <= ?'
        params.append(end_date.isoformat())
    
    query += ' ORDER BY created_at DESC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def _execute_note_search(keyword, tag=None, category=None, start_date=None, end_date=None):
    """执行笔记搜索（可复用，记录搜索历史）"""
    notes = search_notes(keyword, tag, category, start_date, end_date)
    
    filters = {}
    if tag: filters['tag'] = tag
    if category: filters['category'] = category
    if start_date: filters['start_date'] = start_date.isoformat()
    if end_date: filters['end_date'] = end_date.isoformat()
    
    record_search(keyword or '', 'note', len(notes), filters if filters else None)
    
    return notes, filters


def delete_note(note_id):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def add_template(name, content):
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT INTO templates (name, content)
        VALUES (?, ?)
        ''', (name, content))
    except sqlite3.IntegrityError:
        conn.close()
        return False
    
    template_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return template_id


def list_templates():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM templates ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def get_template(name):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM templates WHERE name = ?', (name,))
    row = cursor.fetchone()
    conn.close()
    
    return row


def delete_template(name):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM templates WHERE name = ?', (name,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def display_notes(notes):
    if not notes:
        console.print("[yellow]没有找到笔记[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=6)
    table.add_column("分类", width=12)
    table.add_column("内容", overflow="fold")
    table.add_column("标签", width=15)
    table.add_column("创建时间", width=20)
    
    for note in notes:
        preview = note['content'][:80] + '...' if len(note['content']) > 80 else note['content']
        table.add_row(
            str(note['id']),
            note['category'] or '普通',
            preview,
            note['tags'] or '-',
            format_datetime(datetime.fromisoformat(note['created_at']))
        )
    
    console.print(table)


@click.group()
def note():
    """笔记管理"""
    pass


@note.command()
@click.argument('content', nargs=-1, required=True)
@click.option('-c', '--category', help='笔记分类')
@click.option('-t', '--tags', help='标签，用逗号分隔')
@click.option('--template', 'template_name', help='使用的模板名称')
def add(content, category, tags, template_name):
    """新增笔记"""
    full_content = ' '.join(content)
    
    if template_name:
        template = get_template(template_name)
        if template:
            full_content = template['content'].replace('{{content}}', full_content)
        else:
            console.print(f"[yellow]模板 '{template_name}' 不存在，使用普通笔记格式[/yellow]")
    
    note_id = add_note(full_content, category, tags, template_name)
    console.print(f"[green]✓ 笔记已创建，ID: {note_id}[/green]")


@note.command()
@click.argument('content', nargs=-1, required=True)
def quick(content):
    """快速记录临时笔记"""
    full_content = ' '.join(content)
    note_id = add_note(full_content, category='临时')
    console.print(f"[green]✓ 快速笔记已创建，ID: {note_id}[/green]")


@note.command('list')
@click.option('-c', '--category', help='按分类过滤')
@click.option('-t', '--tag', help='按标签过滤')
@click.option('-n', '--limit', type=int, default=50, help='显示数量限制')
def list_cmd(category, tag, limit):
    """列出笔记"""
    notes = list_notes(category, tag, limit)
    display_notes(notes)


@note.command()
@click.argument('keyword', required=False)
@click.option('-t', '--tag', help='按标签筛选')
@click.option('-c', '--category', help='按分类筛选')
@click.option('--start', help='开始日期 (YYYY-MM-DD)')
@click.option('--end', help='结束日期 (YYYY-MM-DD)')
def search(keyword, tag, category, start, end):
    """搜索笔记（支持标签、分类、日期范围筛选）"""
    from ..utils import parse_date, format_date
    
    start_date = parse_date(start) if start else None
    end_date = parse_date(end) if end else None
    
    notes, filters = _execute_note_search(keyword, tag, category, start_date, end_date)
    
    filter_desc = []
    if keyword: filter_desc.append(f"关键词: {keyword}")
    if tag: filter_desc.append(f"标签: {tag}")
    if category: filter_desc.append(f"分类: {category}")
    if start_date: filter_desc.append(f"开始: {format_date(start_date)}")
    if end_date: filter_desc.append(f"结束: {format_date(end_date)}")
    
    if not notes:
        desc = ", ".join(filter_desc) if filter_desc else "无筛选条件"
        console.print(Panel(
            f"[dim]没有找到匹配的笔记[/dim]\n\n"
            f"筛选条件: {desc}\n"
            "试试其他关键词，或使用 [cyan]eff note list[/cyan] 查看所有笔记",
            title="🔍 搜索结果", border_style="dim"
        ))
    else:
        desc = ", ".join(filter_desc) if filter_desc else "全部笔记"
        console.print(f"[dim]找到 {len(notes)} 条匹配的笔记 ({desc})[/dim]")
        _display_search_results(notes)


@note.command()
@click.option('-r', '--run', is_flag=True, help='直接运行上次搜索')
def last(run):
    """查看或复用上次搜索（带筛选条件）"""
    last = get_last_search('note')
    
    if not last:
        console.print(Panel(
            "[dim]还没有搜索记录[/dim]\n\n"
            "使用 [cyan]eff note search <关键词>[/cyan] 开始搜索",
            title="🔍 最近搜索", border_style="dim"
        ))
        return
    
    keyword = last['keyword']
    hit_count = last['hit_count']
    searched_at = datetime.fromisoformat(last['created_at'])
    filters = last.get('filters', {})
    
    console.print(f"[bold]🔍 上次笔记搜索[/bold]\n")
    console.print(f"  关键词: [cyan]{keyword or '无'}[/cyan]")
    console.print(f"  命中数: {hit_count}")
    console.print(f"  搜索时间: {format_datetime(searched_at)}")
    
    if filters:
        console.print(f"\n[bold]  筛选条件:[/bold]")
        if filters.get('tag'): console.print(f"    标签: {filters['tag']}")
        if filters.get('category'): console.print(f"    分类: {filters['category']}")
        if filters.get('start_date'): console.print(f"    开始日期: {filters['start_date']}")
        if filters.get('end_date'): console.print(f"    结束日期: {filters['end_date']}")
    
    if run:
        console.print(f"\n[cyan]正在重新搜索（带筛选条件）...[/cyan]\n")
        from ..utils import parse_date, format_date
        tag = filters.get('tag')
        category = filters.get('category')
        start_date = parse_date(filters['start_date']) if filters.get('start_date') else None
        end_date = parse_date(filters['end_date']) if filters.get('end_date') else None
        
        notes, _ = _execute_note_search(keyword, tag, category, start_date, end_date)
        
        filter_desc = []
        if keyword: filter_desc.append(f"关键词: {keyword}")
        if tag: filter_desc.append(f"标签: {tag}")
        if category: filter_desc.append(f"分类: {category}")
        if start_date: filter_desc.append(f"开始: {format_date(start_date)}")
        if end_date: filter_desc.append(f"结束: {format_date(end_date)}")
        
        if not notes:
            desc = ", ".join(filter_desc) if filter_desc else "无筛选条件"
            console.print(Panel(
                f"[dim]没有找到匹配的笔记[/dim]\n\n"
                f"筛选条件: {desc}",
                title="🔍 搜索结果", border_style="dim"
            ))
        else:
            desc = ", ".join(filter_desc) if filter_desc else "全部笔记"
            console.print(f"[dim]找到 {len(notes)} 条匹配的笔记 ({desc})[/dim]")
            _display_search_results(notes)


@note.command()
@click.argument('note_id', type=int)
def show(note_id):
    """显示笔记详情"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM notes WHERE id = ?', (note_id,))
    note = cursor.fetchone()
    conn.close()
    
    if not note:
        console.print(f"[red]✗ 笔记 {note_id} 不存在[/red]")
        return
    
    console.print(Panel(note['content'], title=f"笔记 #{note['id']}", border_style="cyan"))
    console.print(f"\n分类: {note['category'] or '普通'}")
    if note['tags']:
        console.print(f"标签: {note['tags']}")
    if note['template_name']:
        console.print(f"模板: {note['template_name']}")
    console.print(f"创建时间: {format_datetime(datetime.fromisoformat(note['created_at']))}")
    console.print(f"更新时间: {format_datetime(datetime.fromisoformat(note['updated_at']))}")


@note.command()
@click.argument('note_id', type=int)
def delete(note_id):
    """删除笔记"""
    if Confirm.ask(f"确定要删除笔记 {note_id} 吗？"):
        if delete_note(note_id):
            console.print(f"[green]✓ 笔记已删除[/green]")
        else:
            console.print(f"[red]✗ 笔记 {note_id} 不存在[/red]")


@note.command()
@click.argument('note_id', type=int)
@click.argument('new_content', nargs=-1, required=True)
def edit(note_id, new_content):
    """编辑笔记"""
    full_content = ' '.join(new_content)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    UPDATE notes 
    SET content = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    ''', (full_content, note_id))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    if updated:
        console.print(f"[green]✓ 笔记已更新[/green]")
    else:
        console.print(f"[red]✗ 笔记 {note_id} 不存在[/red]")


@note.command()
@click.option('-d', '--days', type=int, default=7, help='显示最近N天的历史')
def history(days):
    """查看搜索历史（最近创建的笔记）"""
    from datetime import timedelta
    start_date = date.today() - timedelta(days=days)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM notes 
    WHERE DATE(created_at) >= ?
    ORDER BY created_at DESC
    ''', (start_date.isoformat(),))
    
    notes = cursor.fetchall()
    conn.close()
    
    console.print(f"[bold]📝 最近 {days} 天的笔记历史[/bold]\n")
    display_notes(notes)


@note.group()
def template():
    """快捷模板管理"""
    pass


@template.command()
@click.argument('name')
@click.argument('content', nargs=-1, required=True)
def add(name, content):
    """添加模板，使用 {{content}} 作为内容占位符"""
    full_content = ' '.join(content)
    
    template_id = add_template(name, full_content)
    if template_id:
        console.print(f"[green]✓ 模板已创建: {name}[/green]")
    else:
        console.print(f"[red]✗ 模板 '{name}' 已存在[/red]")


@template.command('list')
def list_template():
    """列出所有模板"""
    templates = list_templates()
    
    if not templates:
        console.print("[yellow]没有找到模板[/yellow]")
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("名称", width=15)
    table.add_column("内容", overflow="fold")
    
    for t in templates:
        preview = t['content'][:60] + '...' if len(t['content']) > 60 else t['content']
        table.add_row(t['name'], preview)
    
    console.print(table)


@template.command()
@click.argument('name')
def show(name):
    """显示模板详情"""
    template = get_template(name)
    
    if not template:
        console.print(f"[red]✗ 模板 '{name}' 不存在[/red]")
        return
    
    console.print(Panel(template['content'], title=f"模板: {name}", border_style="cyan"))


@template.command()
@click.argument('name')
def delete(name):
    """删除模板"""
    if Confirm.ask(f"确定要删除模板 '{name}' 吗？"):
        if delete_template(name):
            console.print(f"[green]✓ 模板已删除[/green]")
        else:
            console.print(f"[red]✗ 模板 '{name}' 不存在[/red]")


@template.command()
@click.argument('name')
@click.argument('content', nargs=-1, required=True)
def use(name, content):
    """使用模板快速创建笔记"""
    template = get_template(name)
    if not template:
        console.print(f"[red]✗ 模板 '{name}' 不存在[/red]")
        return
    
    full_content = ' '.join(content)
    note_content = template['content'].replace('{{content}}', full_content)
    
    note_id = add_note(note_content, template_name=name)
    console.print(f"[green]✓ 使用模板创建笔记，ID: {note_id}[/green]")
    console.print(Panel(note_content, title="笔记内容", border_style="cyan"))
