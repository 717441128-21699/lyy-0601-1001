import click
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..database import get_connection
from ..search_history import (
    get_search_history, get_popular_keywords, 
    get_last_search, clear_search_history, get_search_by_id, record_search
)
from ..utils import format_datetime

console = Console()


def _execute_task_search(keyword, filters=None):
    """执行任务搜索（支持筛选条件）"""
    from .task import _execute_task_search as do_task_search
    from ..utils import parse_date, format_date, get_status_label
    
    filters = filters or {}
    
    tag = filters.get('tag')
    status = filters.get('status')
    start_date = parse_date(filters['start_date']) if filters.get('start_date') else None
    end_date = parse_date(filters['end_date']) if filters.get('end_date') else None
    
    tasks, _ = do_task_search(keyword, tag, status, start_date, end_date)
    
    filter_desc = []
    if keyword: filter_desc.append(f"关键词: {keyword}")
    if tag: filter_desc.append(f"标签: {tag}")
    if status: filter_desc.append(f"状态: {get_status_label(status)}")
    if start_date: filter_desc.append(f"开始: {format_date(start_date)}")
    if end_date: filter_desc.append(f"结束: {format_date(end_date)}")
    
    if not tasks:
        desc = ", ".join(filter_desc) if filter_desc else "无筛选条件"
        console.print(Panel(
            f"[dim]没有找到匹配的任务[/dim]\n\n"
            f"筛选条件: {desc}\n"
            "试试其他关键词，或使用 [cyan]eff task list[/cyan] 查看所有任务",
            title="🔍 搜索结果", border_style="dim"
        ))
    else:
        from .task import display_tasks
        desc = ", ".join(filter_desc) if filter_desc else "全部任务"
        console.print(f"[dim]找到 {len(tasks)} 个匹配的任务 ({desc})[/dim]")
        display_tasks(tasks)


def _execute_note_search(keyword, filters=None):
    """执行笔记搜索（支持筛选条件）"""
    from .note import _execute_note_search as do_note_search
    from ..utils import parse_date, format_date
    
    filters = filters or {}
    
    tag = filters.get('tag')
    category = filters.get('category')
    start_date = parse_date(filters['start_date']) if filters.get('start_date') else None
    end_date = parse_date(filters['end_date']) if filters.get('end_date') else None
    
    notes, _ = do_note_search(keyword, tag, category, start_date, end_date)
    
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
        from .note import _display_search_results
        desc = ", ".join(filter_desc) if filter_desc else "全部笔记"
        console.print(f"[dim]找到 {len(notes)} 条匹配的笔记 ({desc})[/dim]")
        _display_search_results(notes)


def run_search(record):
    """根据搜索记录执行搜索（带筛选条件）"""
    if not record:
        console.print("[red]✗ 没有找到搜索记录[/red]")
        return
    
    keyword = record['keyword']
    search_type = record['search_type']
    filters = record.get('filters', {})
    type_label = {'task': '任务', 'note': '笔记'}[search_type]
    
    filter_parts = []
    if filters:
        for k, v in filters.items():
            k_label = {'tag': '标签', 'status': '状态', 'category': '分类', 'start_date': '开始', 'end_date': '结束'}[k]
            filter_parts.append(f"{k_label}: {v}")
    
    filter_str = f" (筛选: {', '.join(filter_parts)})" if filter_parts else ""
    
    console.print(f"\n[cyan]正在重新搜索 {type_label}: {keyword or '无'}{filter_str}[/cyan]\n")
    
    if search_type == 'task':
        _execute_task_search(keyword, filters)
    elif search_type == 'note':
        _execute_note_search(keyword, filters)


@click.group()
def search():
    """搜索历史管理"""
    pass


@search.command()
@click.option('-t', '--type', 'search_type', 
              type=click.Choice(['task', 'note', 'all']), 
              default='all', help='搜索类型')
@click.option('-s', '--sort', 'sort_by',
              type=click.Choice(['recent', 'popular']),
              default='recent', help='排序方式：recent(最近) / popular(最多用)')
@click.option('-k', '--keyword', help='按关键词过滤')
@click.option('-n', '--limit', type=int, default=20, help='显示数量限制')
@click.option('-r', '--run', 'run_id', type=int, help='通过ID直接运行搜索')
def history(search_type, sort_by, keyword, limit, run_id):
    """查看搜索历史"""
    if run_id is not None:
        record = get_search_by_id(run_id)
        if not record:
            console.print(f"[red]✗ 搜索记录 ID {run_id} 不存在[/red]")
            return
        run_search(record)
        return
    
    st = None if search_type == 'all' else search_type
    records = get_search_history(st, sort_by, keyword, limit)
    
    if not records:
        type_label = '所有' if search_type == 'all' else search_type
        console.print(Panel(
            f"[dim]没有{type_label}搜索历史记录[/dim]\n\n"
            "使用 [cyan]eff task search[/cyan] 或 [cyan]eff note search[/cyan] 开始搜索\n"
            "使用 [cyan]eff search history -r <ID>[/cyan] 直接复用历史搜索",
            title="🔍 搜索历史", border_style="dim"
        ))
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    
    if sort_by == 'popular':
        table.add_column("关键词", overflow="fold")
        table.add_column("类型", width=8)
        table.add_column("搜索次数", width=10)
        table.add_column("总命中数", width=10)
        table.add_column("上次搜索", width=20)
        
        for r in records:
            type_label = {'task': '任务', 'note': '笔记'}.get(r['search_type'], r['search_type'])
            table.add_row(
                r['keyword'],
                type_label,
                str(r['search_count']),
                str(r['total_hits']),
                format_datetime(datetime.fromisoformat(r['last_searched']))
            )
    else:
        table.add_column("编号", style="dim", width=6)
        table.add_column("类型", width=6)
        table.add_column("关键词", overflow="fold")
        table.add_column("命中", width=6)
        table.add_column("筛选条件", overflow="fold")
        table.add_column("搜索时间", width=20)
        
        id_map = {}
        for idx, r in enumerate(records, 1):
            id_map[idx] = r['id']
            type_label = {'task': '任务', 'note': '笔记'}.get(r['search_type'], r['search_type'])
            filters = r.get('filters', {})
            filter_strs = []
            if filters:
                for k, v in filters.items():
                    k_short = {'tag': '标签', 'status': '状态', 'category': '分类', 'start_date': '开始', 'end_date': '结束'}[k]
                    filter_strs.append(f"{k_short}:{v}")
            filter_display = ", ".join(filter_strs) if filter_strs else "-"
            table.add_row(
                str(idx),
                type_label,
                r['keyword'] or "(无关键词)",
                str(r['hit_count']),
                filter_display,
                format_datetime(datetime.fromisoformat(r['created_at']))
            )
    
    sort_label = {'recent': '最近搜索', 'popular': '热门搜索'}[sort_by]
    type_label = '所有' if search_type == 'all' else {'task': '任务', 'note': '笔记'}[search_type]
    
    console.print(f"[bold]🔍 {type_label}{sort_label}历史[/bold]\n")
    console.print(table)
    
    if sort_by == 'recent' and records:
        console.print(f"\n[dim]💡 输入编号直接复用搜索，或按回车退出[/dim]")
        try:
            choice = click.prompt("", prompt_suffix="> ", default="", show_default=False)
            if choice.strip():
                try:
                    idx = int(choice.strip())
                    if idx in id_map:
                        record = get_search_by_id(id_map[idx])
                        if record:
                            run_search(record)
                    else:
                        console.print(f"[yellow]⚠ 编号 {idx} 不在范围内[/yellow]")
                except ValueError:
                    console.print(f"[yellow]⚠ 请输入有效的编号[/yellow]")
        except (EOFError, KeyboardInterrupt):
            pass


@search.command()
@click.option('-t', '--type', 'search_type', 
              type=click.Choice(['task', 'note', 'all']), 
              default='all', help='搜索类型')
@click.option('-n', '--limit', type=int, default=10, help='显示数量限制')
def popular(search_type, limit):
    """查看热门搜索关键词"""
    st = None if search_type == 'all' else search_type
    keywords = get_popular_keywords(st, limit)
    
    if not keywords:
        type_label = '所有' if search_type == 'all' else search_type
        console.print(Panel(
            f"[dim]没有{type_label}搜索记录[/dim]\n\n"
            "开始搜索后这里会显示热门关键词",
            title="🔥 热门搜索", border_style="dim"
        ))
        return
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", width=4)
    table.add_column("关键词", overflow="fold")
    table.add_column("类型", width=8)
    table.add_column("搜索次数", width=10)
    table.add_column("总命中数", width=10)
    
    for i, kw in enumerate(keywords, 1):
        type_label = {'task': '任务', 'note': '笔记'}.get(kw['search_type'], kw['search_type'])
        table.add_row(
            str(i),
            kw['keyword'],
            type_label,
            str(kw['search_count']),
            str(kw['total_hits'])
        )
    
    type_label = '所有' if search_type == 'all' else {'task': '任务', 'note': '笔记'}[search_type]
    console.print(f"[bold]🔥 {type_label}热门搜索关键词[/bold]\n")
    console.print(table)


@search.command()
@click.option('-t', '--type', 'search_type', 
              type=click.Choice(['task', 'note', 'all']), 
              default='all', help='搜索类型')
@click.option('-r', '--run', is_flag=True, help='直接运行最近一次搜索')
def last(search_type, run):
    """查看最近一次搜索"""
    st = None if search_type == 'all' else search_type
    last = get_last_search(st)
    
    if not last:
        type_label = '所有' if search_type == 'all' else search_type
        console.print(Panel(
            f"[dim]没有{type_label}搜索记录[/dim]",
            title="🔍 最近搜索", border_style="dim"
        ))
        return
    
    type_label = {'task': '任务', 'note': '笔记'}.get(last['search_type'], last['search_type'])
    
    if run:
        run_search(last)
        return
    
    console.print(f"[bold]🔍 最近一次{type_label}搜索[/bold]\n")
    console.print(f"  关键词: [cyan]{last['keyword']}[/cyan]")
    console.print(f"  命中数: {last['hit_count']}")
    console.print(f"  搜索时间: {format_datetime(datetime.fromisoformat(last['created_at']))}")
    console.print(f"\n[dim]💡 使用 [cyan]eff search last -r[/cyan] 直接重新搜索[/dim]")


@search.command()
@click.option('-t', '--type', 'search_type', 
              type=click.Choice(['task', 'note', 'all']), 
              default='all', help='搜索类型')
@click.option('-d', '--days', type=int, help='只清除N天前的记录')
def clear(search_type, days):
    """清除搜索历史"""
    st = None if search_type == 'all' else search_type
    type_label = '所有' if search_type == 'all' else {'task': '任务', 'note': '笔记'}[search_type]
    
    confirm_msg = f"确定要清除{type_label}搜索历史吗？"
    if days:
        confirm_msg = f"确定要清除{days}天前的{type_label}搜索历史吗？"
    
    if Confirm.ask(confirm_msg):
        deleted = clear_search_history(st, days)
        if deleted > 0:
            console.print(f"[green]✓ 已清除 {deleted} 条搜索记录[/green]")
        else:
            console.print(f"[yellow]没有可清除的搜索记录[/yellow]")
