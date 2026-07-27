#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全网热搜监控 - 每小时整点抓取各平台热搜Top10，推送到企微群
支持平台：微博、抖音、B站、快手、头条
特性：跨平台大热点检测（>=3个平台出现相同关键词时提醒）
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

BJT = timezone(timedelta(hours=8))
WECOM_WEBHOOK = os.getenv('WECOM_WEBHOOK', '')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

TIMEOUT = 10

# 停用词，提取关键词时过滤
STOP_WORDS = {
    '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
    '自己', '这', '他', '她', '它', '们', '那', '被', '从', '把', '让', '用', '为',
    '什么', '怎么', '如何', '哪', '吗', '呢', '吧', '啊', '呀', '嘛', '还', '又',
    '已经', '可以', '这个', '那个', '曝', '称', '回应', '发文', '表示', '官方',
}


def extract_keywords(title):
    """从标题中提取关键词（2字及以上的中文词组 + 英文/数字词）"""
    # 去除方括号标签如 [热] [新] [沸]
    title = re.sub(r'\[.*?\]', '', title)
    # 提取中文段落和英文/数字段落
    segments = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+', title)
    keywords = set()
    for seg in segments:
        if seg.lower() in STOP_WORDS or seg in STOP_WORDS:
            continue
        if len(seg) >= 2:
            keywords.add(seg)
    return keywords


def detect_hot_topics(all_data):
    """
    检测跨平台大热点
    返回：出现在>=3个平台的关键词及其出现平台列表
    """
    # keyword -> set of platforms
    keyword_platforms = defaultdict(set)
    # keyword -> 完整标题示例（取第一个匹配的）
    keyword_example = {}

    platform_names = {
        'weibo': '微博', 'douyin': '抖音', 'bilibili': 'B站',
        'kuaishou': '快手', 'toutiao': '头条'
    }

    for platform, items in all_data.items():
        for item in items:
            title = item.get('title', '')
            kws = extract_keywords(title)
            for kw in kws:
                keyword_platforms[kw].add(platform)
                if kw not in keyword_example:
                    keyword_example[kw] = title

    # 筛选出现在3个及以上平台的关键词
    hot_topics = []
    for kw, platforms in keyword_platforms.items():
        if len(platforms) >= 3:
            pnames = [platform_names.get(p, p) for p in platforms]
            hot_topics.append({
                'keyword': kw,
                'platforms': pnames,
                'count': len(platforms),
                'example': keyword_example.get(kw, '')
            })

    # 按覆盖平台数降序，再按关键词长度降序（长词更有意义）
    hot_topics.sort(key=lambda x: (x['count'], len(x['keyword'])), reverse=True)
    return hot_topics


def fetch_weibo():
    """微博热搜 - weibo.com/ajax/side/hotSearch"""
    url = 'https://weibo.com/ajax/side/hotSearch'
    try:
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://weibo.com/'}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        realtime = data.get('data', {}).get('realtime', [])
        results = []
        for i, item in enumerate(realtime[:10]):
            title = item.get('word', item.get('note', ''))
            hot = item.get('num', item.get('raw_hot', 0))
            label = item.get('label_name', '')
            prefix = f"[{label}]" if label else ""
            results.append({
                'rank': i + 1,
                'title': f"{prefix}{title}",
                'hot': hot
            })
        return results
    except Exception as e:
        print(f"  [微博] 失败: {e}")
        return []


def fetch_douyin():
    """抖音热搜 - douyin.com/aweme/v1/web/hot/search/list"""
    url = 'https://www.douyin.com/aweme/v1/web/hot/search/list/'
    params = {'device_platform': 'webapp', 'aid': '6383', 'channel': 'channel_pc_web'}
    try:
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.douyin.com/'}, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        word_list = data.get('data', {}).get('word_list', [])
        results = []
        for i, item in enumerate(word_list[:10]):
            title = item.get('word', '')
            hot = item.get('hot_value', 0)
            results.append({
                'rank': i + 1,
                'title': title,
                'hot': hot
            })
        return results
    except Exception as e:
        print(f"  [抖音] 失败: {e}")
        return []


def fetch_bilibili():
    """B站热搜 - app.bilibili.com/x/v2/search/trending/ranking"""
    url = 'https://app.bilibili.com/x/v2/search/trending/ranking'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        trending = data.get('data', {}).get('list', [])
        if not trending:
            url2 = 'https://api.bilibili.com/x/web-interface/wbi/search/square?limit=10'
            resp2 = requests.get(url2, headers=HEADERS, timeout=TIMEOUT)
            data2 = resp2.json()
            trending = data2.get('data', {}).get('trending', {}).get('list', [])
        results = []
        for i, item in enumerate(trending[:10]):
            title = item.get('keyword', item.get('show_name', ''))
            hot = item.get('heat_score', item.get('hot_id', 0))
            results.append({
                'rank': i + 1,
                'title': title,
                'hot': hot
            })
        return results
    except Exception as e:
        print(f"  [B站] 失败: {e}")
        return []


def fetch_kuaishou():
    """快手热搜"""
    try:
        api_url = 'https://www.kuaishou.com/graphql'
        payload = {
            "operationName": "visionHotRank",
            "variables": {"page": "home"},
            "query": "query visionHotRank($page: String) { visionHotRank(page: $page) { items { name hotValue iconUrl } } }"
        }
        session = requests.Session()
        session.headers.update({**HEADERS, 'Referer': 'https://www.kuaishou.com/'})
        resp = session.post(api_url, json=payload, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('data', {}).get('visionHotRank', {}).get('items', [])
        if items:
            results = []
            for i, item in enumerate(items[:10]):
                results.append({
                    'rank': i + 1,
                    'title': item.get('name', ''),
                    'hot': item.get('hotValue', 0)
                })
            return results
    except Exception as e:
        print(f"  [快手] 主接口失败: {e}")

    # 备用
    try:
        url = 'https://tenapi.cn/v2/kuaishouhot'
        resp = requests.get(url, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('data', [])
        results = []
        for i, item in enumerate(items[:10]):
            results.append({
                'rank': i + 1,
                'title': item.get('name', item.get('title', '')),
                'hot': item.get('hot', item.get('hotValue', 0))
            })
        return results if results else []
    except Exception as e:
        print(f"  [快手] 备用接口也失败: {e}")
        return []


def fetch_toutiao():
    """今日头条热搜 - toutiao.com/hot-event/hot-board"""
    url = 'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc'
    try:
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.toutiao.com/'}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('data', [])
        results = []
        for i, item in enumerate(items[:10]):
            title = item.get('Title', item.get('title', ''))
            hot = item.get('HotValue', item.get('hot_value', ''))
            results.append({
                'rank': i + 1,
                'title': title,
                'hot': hot
            })
        return results
    except Exception as e:
        print(f"  [头条] 失败: {e}")
        return []


def format_hot(value):
    """格式化热度值"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if value >= 100000000:
        return f"{value/100000000:.1f}亿"
    if value >= 10000:
        return f"{value/10000:.1f}万"
    return str(value)


def build_message(all_data):
    """构建企微消息"""
    now = datetime.now(BJT).strftime('%m-%d %H:%M')

    lines = [f"🔥 全网热搜播报 | {now}"]

    platform_config = [
        ('weibo', '📱 微博'),
        ('douyin', '🎵 抖音'),
        ('bilibili', '📺 B站'),
        ('kuaishou', '⚡ 快手'),
        ('toutiao', '📰 头条'),
    ]

    success_count = 0
    for platform, name in platform_config:
        data = all_data.get(platform, [])
        if data:
            success_count += 1
            lines.append(f"\n{'─'*18}")
            lines.append(f"{name} Top10")
            for item in data:
                hot_str = format_hot(item['hot'])
                hot_display = f" 🔥{hot_str}" if hot_str else ""
                lines.append(f" {item['rank']:>2}. {item['title']}{hot_display}")

    # 大热点检测
    hot_topics = detect_hot_topics(all_data)
    if hot_topics:
        lines.append(f"\n{'═'*18}")
        lines.append("🚨 大热点提醒（≥3个平台同时在榜）")
        for topic in hot_topics[:5]:  # 最多展示5个大热点
            plist = '、'.join(topic['platforms'])
            lines.append(f"  🔴 「{topic['keyword']}」覆盖{topic['count']}个平台（{plist}）")

    if success_count == 0:
        lines.append("\n⚠️ 所有平台抓取失败")
    else:
        lines.append(f"\n✅ 成功获取 {success_count}/5 个平台")

    return '\n'.join(lines)


def send_wecom(content):
    """发送到企微群"""
    if not WECOM_WEBHOOK:
        print("[WARN] WECOM_WEBHOOK 未配置，跳过发送")
        print("\n--- 消息预览 ---")
        print(content)
        print("--- 结束 ---")
        return False

    webhook_url = WECOM_WEBHOOK
    if not webhook_url.startswith('http'):
        webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_url}"

    payload = {
        "msgtype": "text",
        "text": {"content": content}
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        result = resp.json()
        if result.get('errcode') == 0:
            print("[OK] 企微发送成功")
            return True
        else:
            print(f"[ERR] 企微发送失败: {result}")
            return False
    except Exception as e:
        print(f"[ERR] 企微发送异常: {e}")
        return False


def main():
    print(f"=== 全网热搜监控 ===")
    print(f"Time: {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}")

    all_data = {}

    platforms = [
        ('weibo', '微博', fetch_weibo),
        ('douyin', '抖音', fetch_douyin),
        ('bilibili', 'B站', fetch_bilibili),
        ('kuaishou', '快手', fetch_kuaishou),
        ('toutiao', '头条', fetch_toutiao),
    ]

    for key, name, fetcher in platforms:
        print(f"\n[{name}] 抓取中...")
        data = fetcher()
        all_data[key] = data
        count = len(data)
        if count > 0:
            print(f"  ✅ 获取 {count} 条")
        else:
            print(f"  ❌ 获取失败")
        time.sleep(0.5)

    # 构建消息并发送
    message = build_message(all_data)

    # 统计
    total = sum(len(v) for v in all_data.values())
    print(f"\n总计获取 {total} 条热搜")

    # 大热点日志
    hot_topics = detect_hot_topics(all_data)
    if hot_topics:
        print(f"检测到 {len(hot_topics)} 个大热点（>=3平台）")
        for t in hot_topics[:5]:
            print(f"  - {t['keyword']} ({t['count']}平台)")

    if total > 0:
        send_wecom(message)
    else:
        print("[SKIP] 无数据，跳过发送")
        sys.exit(1)


if __name__ == '__main__':
    main()
