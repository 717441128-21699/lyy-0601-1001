import json
from datetime import datetime
from .database import get_connection
from .search_history import parse_filters


def save_search(name, search_type, keyword=None, filters=None):
    """保存搜索为常用搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    filters_json = json.dumps(filters, ensure_ascii=False) if filters else None
    
    try:
        cursor.execute('''
        INSERT INTO saved_searches (name, search_type, keyword, filters, last_used_at)
        VALUES (?, ?, ?, ?, ?)
        ''', (name, search_type, keyword, filters_json, datetime.now().isoformat()))
    except Exception as e:
        if 'UNIQUE constraint failed' in str(e):
            conn.close()
            return False, "名称已存在，请使用其他名称"
        conn.close()
        return False, str(e)
    
    conn.commit()
    conn.close()
    
    return True, None


def list_saved_searches(search_type=None):
    """列出所有常用搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM saved_searches'
    params = []
    
    if search_type:
        query += ' WHERE search_type = ?'
        params.append(search_type)
    
    query += ' ORDER BY last_used_at DESC, created_at DESC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        row_dict = dict(row)
        row_dict['filters'] = parse_filters(row_dict.get('filters'))
        result.append(row_dict)
    
    return result


def get_saved_search(name):
    """获取指定名称的常用搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM saved_searches WHERE name = ?', (name,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute('UPDATE saved_searches SET last_used_at = ? WHERE name = ?',
                       (datetime.now().isoformat(), name))
        conn.commit()
    
    conn.close()
    
    if row:
        row_dict = dict(row)
        row_dict['filters'] = parse_filters(row_dict.get('filters'))
        return row_dict
    
    return None


def delete_saved_search(name):
    """删除常用搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM saved_searches WHERE name = ?', (name,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def run_saved_search(name):
    """运行常用搜索，返回搜索记录字典用于执行"""
    saved = get_saved_search(name)
    if not saved:
        return None
    
    return {
        'keyword': saved['keyword'],
        'search_type': saved['search_type'],
        'filters': saved['filters']
    }
