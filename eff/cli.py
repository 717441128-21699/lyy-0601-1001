#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .database import init_db
from .commands.task import task
from .commands.plan import plan
from .commands.focus import focus
from .commands.note import note
from .commands.review import review
from .commands.stats import stats
from .commands.sync import sync
from .commands.config import config
from .commands.search import search

import click


@click.group()
@click.version_option(version='1.0.0', prog_name='eff')
@click.pass_context
def cli(ctx):
    """个人效率命令行工具 - 为键盘用户设计
    
    命令速查:
      task    任务管理
      plan    计划管理
      focus   番茄钟专注
      note    笔记管理
      review  复盘分析
      stats   统计分析
      sync    数据同步
      config  配置管理
    """
    init_db()
    ctx.ensure_object(dict)


cli.add_command(task)
cli.add_command(plan)
cli.add_command(focus)
cli.add_command(note)
cli.add_command(review)
cli.add_command(stats)
cli.add_command(sync)
cli.add_command(config)
cli.add_command(search)


@cli.command()
@click.pass_context
def dashboard(ctx):
    """显示今日仪表盘"""
    from .commands.stats import stats
    ctx.invoke(stats.commands['summary'])
    
    from .commands.stats import get_overdue_tasks
    overdue = get_overdue_tasks()
    if overdue:
        click.echo()
        click.echo(f"⚠️  有 {len(overdue)} 个逾期任务需要处理")


if __name__ == '__main__':
    cli()
