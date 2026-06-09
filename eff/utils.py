from datetime import datetime, date, timedelta
from dateutil import parser as date_parser
from .config import get_config_value


def parse_date(date_str):
    if not date_str:
        return None
    
    today = date.today()
    
    if date_str.lower() == 'today':
        return today
    elif date_str.lower() == 'tomorrow':
        return today + timedelta(days=1)
    elif date_str.lower() == 'yesterday':
        return today - timedelta(days=1)
    
    try:
        parsed = date_parser.parse(date_str)
        return parsed.date()
    except (ValueError, TypeError):
        return None


def parse_datetime(datetime_str):
    if not datetime_str:
        return None
    try:
        return date_parser.parse(datetime_str)
    except (ValueError, TypeError):
        return None


def format_date(d):
    if not d:
        return ''
    fmt = get_config_value('date_format')
    return d.strftime(fmt)


def format_datetime(dt):
    if not dt:
        return ''
    date_fmt = get_config_value('date_format')
    time_fmt = get_config_value('time_format')
    return dt.strftime(f"{date_fmt} {time_fmt}")


def format_duration(minutes):
    if not minutes:
        return '0m'
    hours = minutes // 60
    mins = minutes % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0:
        parts.append(f"{mins}m")
    return ' '.join(parts) if parts else '0m'


def get_priority_label(priority):
    labels = {4: '🔴 紧急', 3: '🟠 高', 2: '🟡 中', 1: '🟢 低'}
    return labels.get(priority, '🟢 低')


def get_status_label(status):
    labels = {
        'pending': '⏳ 待办',
        'in_progress': '🔄 进行中',
        'completed': '✅ 完成',
        'cancelled': '❌ 取消'
    }
    return labels.get(status, status)


def get_week_range(date_obj=None):
    if date_obj is None:
        date_obj = date.today()
    
    start = date_obj - timedelta(days=date_obj.weekday())
    end = start + timedelta(days=6)
    return start, end


def is_overdue(due_date, status='pending'):
    if not due_date or status == 'completed':
        return False
    return due_date < date.today()


def parse_tags(tags_str):
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(',') if t.strip()]


def tags_to_str(tags):
    if not tags:
        return ''
    return ','.join(tags)


def get_date_range(range_type, start=None, end=None):
    """获取日期范围
    
    range_type: today, week, month, custom
    """
    today = date.today()
    
    if range_type == 'today':
        return today, today
    elif range_type == 'week':
        return get_week_range(today)
    elif range_type == 'month':
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        return start, end
    elif range_type == 'custom' and start and end:
        s = parse_date(start)
        e = parse_date(end)
        if s and e:
            return s, e
    
    return today, today


def get_range_label(range_type, start_date=None, end_date=None):
    """获取日期范围的显示标签"""
    labels = {
        'today': '今日',
        'week': '本周',
        'month': '本月',
        'custom': '自定义'
    }
    
    label = labels.get(range_type, range_type)
    
    if range_type == 'custom' and start_date and end_date:
        label = f"{format_date(start_date)} 至 {format_date(end_date)}"
    
    return label
