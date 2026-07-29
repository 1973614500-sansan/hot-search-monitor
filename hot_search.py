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

STOP_WORDS = {
    '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '上', '也', '而', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
    '自己', '这', '他', '她', '本', '此', '它', '后', '前', '中', '很', '能', '为',
    '什么', '怎么', '哪个', '那', '只', '其', '还', '让', '呀', '吧', '被', '比',
    '已经', '因为', '当前', '那个', '从', '于', '应该', '可以', '表示', '官方',
    '虽然', '当然', '可能', '原来', '其实', '大家', '直接', '突然', '近日',
}


def extract_keywords(title):
    title = re.sub(r'\[.*?\]', '', title)
    segments = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+', title)
    keywords = set()
    for seg in segments:
        if seg.isdigit():
            continue
        if seg.isascii() and len(seg) < 3:
            continue
        if seg.lower() in STOP_WORDS or seg in STOP_WORDS:
            continue
        if len(seg) >= 2:
            keywords.add(seg)
    return keywords


def detect_hot_topics(all_data):
    keyword_platforms = defaultdict(set)
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
    hot_topics.sort(key=lambda x: (x['count'], len(x['keyword'])), reverse=True)
    return hot_topics


def fetch_weibo():
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
            results.append({'rank': i + 1, 'title': f"{prefix}{title}", 'hot': hot})
        return results
    except Exception as e:
        print(f"  [微博] 失败: {e}")
        return []


def fetch_douyin():
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
            results.append({'rank': i + 1, 'title': title, 'hot': hot})
        return results
    except Exception as e:
        print(f"  [抖音] 失败: {e}")
        return []


def fetch_bilibili():
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
            results.append({'rank': i + 1, 'title': title, 'hot': hot})
        return results
    except Exception as e:
        print(f"  [B站] 失败: {e}")
        return []


def fetch_kuaishou():
    apis = [
        ('https://www.kuaishou.com/graphql', 'graphql'),
        ('https://api.vvhan.com/api/hotlist/kuaiShou', 'vvhan'),
        ('https://tenapi.cn/v2/kuaishouhot', 'tenapi'),
        ('https://api.oioweb.cn/api/common/HotList?type=kuaishou', 'oioweb'),
    ]
    # Try GraphQL first
    try:
        payload = {"operationName": "visionHotRank", "variables": {"page": "home"}}
        payload["query"] = "query visionHotRank(" + chr(36) + "page: String) { visionHotRank(page: " + chr(36) + "page) { items { name hotValue iconUrl } } }"
        session = requests.Session()
        session.headers.update({**HEADERS, 'Referer': 'https://www.kuaishou.com/'})
        resp = session.post('https://www.kuaishou.com/graphql', json=payload, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('data', {}).get('visionHotRank', {}).get('items', [])
        if items:
            results = []
            for i, item in enumerate(items[:10]):
                results.append({'rank': i + 1, 'title': item.get('name', ''), 'hot': item.get('hotValue', 0)})
            print("  [\u5feb\u624b] GraphQL\u6210\u529f")
            return results
    except Exception as e:
        print(f"  [\u5feb\u624b] GraphQL\u5931\u8d25: {e}")

    # Try vvhan
    try:
        resp = requests.get('https://api.vvhan.com/api/hotlist/kuaiShou', headers=HEADERS, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('data', [])
        if items:
            results = []
            for i, item in enumerate(items[:10]):
                results.append({'rank': i + 1, 'title': item.get('title', ''), 'hot': item.get('hot', 0)})
            print("  [\u5feb\u624b] vvhan\u6210\u529f")
            return results
    except Exception as e:
        print(f"  [\u5feb\u624b] vvhan\u5931\u8d25: {e}")

    # Try tenapi
    try:
        resp = requests.get('https://tenapi.cn/v2/kuaishouhot', headers=HEADERS, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('data', [])
        if items:
            results = []
            for i, item in enumerate(items[:10]):
                results.append({'rank': i + 1, 'title': item.get('name', item.get('title', '')), 'hot': item.get('hot', item.get('hotValue', 0))})
            print("  [\u5feb\u624b] tenapi\u6210\u529f")
            return results
    except Exception as e:
        print(f"  [\u5feb\u624b] tenapi\u5931\u8d25: {e}")

    # Try oioweb
    try:
        resp = requests.get('https://api.oioweb.cn/api/common/HotList?type=kuaishou', headers=HEADERS, timeout=TIMEOUT)
        data = resp.json()
        items = data.get('result', data.get('data', []))
        if items:
            results = []
            for i, item in enumerate(items[:10]):
                results.append({'rank': i + 1, 'title': item.get('title', ''), 'hot': item.get('hot', 0)})
            print("  [\u5feb\u624b] oioweb\u6210\u529f")
            return results
    except Exception as e:
        print(f"  [\u5feb\u624b] oioweb\u5931\u8d25: {e}")

    print("  [\u5feb\u624b] \u6240\u6709\u63a5\u53e3\u5747\u5931\u8d25")
    return []

def fetch_toutiao():
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
            results.append({'rank': i + 1, 'title': title, 'hot': hot})
        return results
    except Exception as e:
        print(f"  [头条] 失败: {e}")
        return []


def format_hot(value):
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
            lines.append(f"\n{chr(9472)*18}")
            lines.append(f"{name} Top10")
            for item in data:
                hot_str = format_hot(item['hot'])
                hot_display = f" 🔥{hot_str}" if hot_str else ""
                lines.append(f"  {item['rank']:>2}. {item['title']}{hot_display}")
    hot_topics = detect_hot_topics(all_data)
    if hot_topics:
        lines.append(f"\n{chr(9552)*18}")
        lines.append("🚨 大热点提醒（≥3个平台同时在榜）")
        for topic in hot_topics[:5]:
            plist = '、'.join(topic['platforms'])
            lines.append(f"  🔴 『{topic['keyword']}』覆盖{topic['count']}个平台（{plist}）")
    if success_count == 0:
        lines.append("\n⚠️ 所有平台抓取失败")
    else:
        lines.append(f"\n✅ 成功获取 {success_count}/5 个平台")
    return "\n".join(lines)


def send_wecom(content):
    if not WECOM_WEBHOOK:
        print('[WARN] WECOM_WEBHOOK 未配置，跳过发送')
        print("\n--- 消息预览 ---")
        print(content)
        print('--- 结束 ---')
        return False
    webhook_url = WECOM_WEBHOOK
    if not webhook_url.startswith('http'):
        webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_url}"
    payload = {
        "msgtype": "text",
        "text": {
            "content": content,
            "mentioned_list": ["liyijie01", "hujianing"],
            "mentioned_mobile_list": ["13810767926", "18794202126"]
        }
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        result = resp.json()
        if result.get('errcode') == 0:
            print('[OK] 企微发送成功')
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
            print(f"  获取 {count} 条")
        else:
            print(f"  获取失败")
        time.sleep(0.5)
    message = build_message(all_data)
    total = sum(len(v) for v in all_data.values())
    print(f"\n总计获取 {total} 条数据")
    hot_topics = detect_hot_topics(all_data)
    if hot_topics:
        print(f"检测到 {len(hot_topics)} 个大热点（>=3平台）")
        for t in hot_topics[:5]:
            print(f"  - {t['keyword']} ({t['count']}平台)")
    if total > 0:
        send_wecom(message)
    else:
        print('[SKIP] 无数据，跳过发送')
        sys.exit(1)


if __name__ == '__main__':
    main()