import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..config import (
    load_config, save_config, get_config_value, set_config_value,
    get_profiles, load_profile, save_profile, delete_profile,
    DEFAULT_CONFIG
)

console = Console()


def format_value(value):
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


@click.group()
def config():
    """配置管理"""
    pass


@config.command('list')
def list_cmd():
    """列出所有配置项"""
    config = load_config()
    
    console.print(f"[bold]⚙️  当前配置[/bold]")
    console.print(f"  配置文件: [dim]{config['current_profile']}[/dim]\n")
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("配置项", width=25)
    table.add_column("值")
    
    for key, value in sorted(config.items()):
        table.add_row(key, format_value(value))
    
    console.print(table)


@config.command()
@click.argument('key')
@click.argument('value')
def set(key, value):
    """设置配置项"""
    if key not in DEFAULT_CONFIG:
        console.print(f"[yellow]警告: '{key}' 不是标准配置项，仍将保存[/yellow]")
    
    try:
        if value.lower() == 'true':
            value = True
        elif value.lower() == 'false':
            value = False
        else:
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass
    except:
        pass
    
    set_config_value(key, value)
    console.print(f"[green]✓ 已设置 {key} = {format_value(value)}[/green]")


@config.command()
@click.argument('key')
def get(key):
    """获取配置项"""
    value = get_config_value(key)
    if value is None:
        console.print(f"[yellow]配置项 '{key}' 不存在[/yellow]")
    else:
        console.print(f"{key} = {format_value(value)}")


@config.command()
@click.argument('key')
def unset(key):
    """删除配置项（恢复默认值）"""
    if key in DEFAULT_CONFIG:
        default_value = DEFAULT_CONFIG[key]
        set_config_value(key, default_value)
        console.print(f"[green]✓ 已恢复 {key} = {format_value(default_value)}[/green]")
    else:
        config = load_config()
        if key in config:
            del config[key]
            save_config(config)
            console.print(f"[green]✓ 已删除配置项 {key}[/green]")
        else:
            console.print(f"[yellow]配置项 '{key}' 不存在[/yellow]")


@config.command()
def reset():
    """重置所有配置为默认值"""
    from rich.prompt import Confirm
    if Confirm.ask("确定要重置所有配置为默认值吗？"):
        save_config(DEFAULT_CONFIG.copy())
        console.print(f"[green]✓ 已重置所有配置[/green]")


@config.group()
def profile():
    """配置文件管理"""
    pass


@profile.command('list')
def profile_list():
    """列出所有配置文件"""
    profiles = get_profiles()
    current = get_config_value('current_profile')
    
    console.print(f"[bold]📁 配置文件列表[/bold]\n")
    
    for p in profiles:
        marker = "← 当前" if p == current else ""
        console.print(f"  {p} {marker}")


@profile.command('use')
@click.argument('name')
def profile_use(name):
    """切换配置文件"""
    try:
        load_profile(name)
        console.print(f"[green]✓ 已切换到配置文件: {name}[/green]")
    except ValueError as e:
        console.print(f"[red]✗ {e}[/red]")


@profile.command('save')
@click.argument('name')
def profile_save(name):
    """保存当前配置为新文件"""
    save_profile(name)
    console.print(f"[green]✓ 已保存配置文件: {name}[/green]")


@profile.command('delete')
@click.argument('name')
def profile_delete(name):
    """删除配置文件"""
    from rich.prompt import Confirm
    if Confirm.ask(f"确定要删除配置文件 '{name}' 吗？"):
        try:
            delete_profile(name)
            console.print(f"[green]✓ 已删除配置文件: {name}[/green]")
        except ValueError as e:
            console.print(f"[red]✗ {e}[/red]")


@config.command()
def path():
    """显示配置文件路径"""
    from ..database import get_config_path, get_db_path
    
    config_path = get_config_path()
    db_path = get_db_path()
    
    console.print(f"[bold]📂 数据存储位置[/bold]\n")
    console.print(f"  配置文件: [cyan]{config_path}[/cyan]")
    console.print(f"  数据库: [cyan]{db_path}[/cyan]")
    console.print(f"  导出目录: [cyan]{get_config_value('export_dir')}[/cyan]")
