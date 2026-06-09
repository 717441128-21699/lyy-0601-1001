from datetime import datetime, date, timedelta
from collections import defaultdict
from .database import get_connection


def record_search(keyword, search_type, hit_count):
    """记录一次搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO search_history (keyword, search_type, hit_count)
    VALUES (?, ?, ?)
    ''', (keyword, search_type, hit_count))
    
    conn.commit()
    conn.close()


def get_last_search(search_type=None):
    """获取最近一次搜索"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM search_history'
    params = []
    
    if search_type:
        query += ' WHERE search_type = ?'
        params.append(search_type)
    
    query += ' ORDER BY created_at DESC LIMIT 1'
    
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    
    return row


def get_search_history(search_type=None, sort_by='recent', keyword_filter=None, limit=50):
    """获取搜索历史
    
    sort_by: 'recent' (最近), 'popular' (最多用)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    if sort_by == 'popular':
        query = '''
        SELECT keyword, search_type, 
               COUNT(*) as search_count, 
               SUM(hit_count) as total_hits,
               MAX(created_at) as last_searched
        FROM search_history
        WHERE 1=1
        '''
        params = []
        
        if search_type:
            query += ' AND search_type = ?'
            params.append(search_type)
        
        if keyword_filter:
            query += ' AND keyword LIKE ?'
            params.append(f'%{keyword_filter}%')
        
        query += ' GROUP BY keyword, search_type ORDER BY search_count DESC, last_searched DESC LIMIT ?'
        params.append(limit)
        
    else:
        query = 'SELECT * FROM search_history WHERE 1=1'
        params = []
        
        if search_type:
            query += ' AND search_type = ?'
            params.append(search_type)
        
        if keyword_filter:
            query += ' AND keyword LIKE ?'
            params.append(f'%{keyword_filter}%')
        
        query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def get_popular_keywords(search_type=None, limit=10):
    """获取热门搜索关键词"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT keyword, 
           COUNT(*) as search_count, 
           SUM(hit_count) as total_hits,
           MAX(created_at) as last_searched
    FROM search_history
    WHERE 1=1
    '''
    params = []
    
    if search_type:
        query += ' AND search_type = ?'
        params.append(search_type)
    
    query += ' GROUP BY keyword ORDER BY search_count DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return rows


def get_search_by_id(search_id):
    """根据ID获取搜索记录"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM search_history WHERE id = ?', (search_id,))
    row = cursor.fetchone()
    conn.close()
    
    return row


def clear_search_history(search_type=None, days=None):
    """清除搜索历史"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'DELETE FROM search_history WHERE 1=1'
    params = []
    
    if search_type:
        query += ' AND search_type = ?'
        params.append(search_type)
    
    if days:
        cutoff = date.today() - timedelta(days=days)
        query += ' AND DATE(created_at) <= ?'
        params.append(cutoff.isoformat())
    
    cursor.execute(query, params)
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    return deleted
