import click
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..database import get_connection
from ..search_history import (
    get_search_history, get_popular_keywords, 
    get_last_search, clear_search_history
)
from ..utils import format_datetime

console = Console()


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
def history(search_type, sort_by, keyword, limit):
    """查看搜索历史"""
    st = None if search_type == 'all' else search_type
    records = get_search_history(st, sort_by, keyword, limit)
    
    if not records:
        type_label = '所有' if search_type == 'all' else search_type
        console.print(Panel(
            f"[dim]没有{type_label}搜索历史记录[/dim]\n\n"
            "使用 [cyan]eff task search[/cyan] 或 [cyan]eff note search[/cyan] 开始搜索",
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
        table.add_column("ID", style="dim", width=6)
        table.add_column("关键词", overflow="fold")
        table.add_column("类型", width=8)
        table.add_column("命中数", width=8)
        table.add_column("搜索时间", width=20)
        
        for r in records:
            type_label = {'task': '任务', 'note': '笔记'}.get(r['search_type'], r['search_type'])
            table.add_row(
                str(r['id']),
                r['keyword'],
                type_label,
                str(r['hit_count']),
                format_datetime(datetime.fromisoformat(r['created_at']))
            )
    
    sort_label = {'recent': '最近搜索', 'popular': '热门搜索'}[sort_by]
    type_label = '所有' if search_type == 'all' else {'task': '任务', 'note': '笔记'}[search_type]
    
    console.print(f"[bold]🔍 {type_label}{sort_label}历史[/bold]\n")
    console.print(table)


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
def last(search_type):
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
    
    console.print(f"[bold]🔍 最近一次{type_label}搜索[/bold]\n")
    console.print(f"  关键词: [cyan]{last['keyword']}[/cyan]")
    console.print(f"  命中数: {last['hit_count']}")
    console.print(f"  搜索时间: {format_datetime(datetime.fromisoformat(last['created_at']))}")


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
