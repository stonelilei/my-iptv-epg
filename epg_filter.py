import xml.etree.ElementTree as ET
import requests
import sys
import re
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区域 ====================
# 1. 你的 IPTV 直播源地址
M3U_URL = "http://hn.wikiapp.uk:5678/tv.m3u?token=cd52e0986f&url=myiptv"

# 2. 你提供的 DIYP 动态接口基础路径
DIYP_BASE_URL = "http://epg.51zmt.top:8000/api/diyp/"

# 3. 生成的精简版文件名
OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_m3u(url):
    """从 M3U 中提取最干净的频道原始显示名称（不作模糊处理，确保请求接口精准）"""
    channels = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=25, verify=False)
        response.encoding = response.apparent_encoding  
        lines = response.text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                # 优先提取逗号后面的标准频道名
                if ',' in line:
                    display_name = line.split(',')[-1].strip()
                    if display_name and not display_name.startswith("#"):
                        channels.add(display_name)
    except Exception as e:
        print(f"❌ 请求 M3U 直播源失败: {e}")
    return channels

def fetch_single_channel_epg(channel_name):
    """单线程：向 DIYP 接口请求单个频道的节目单数据"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    # 构造请求参数，通常 DIYP 接口通过 ?ch= 传入频道名
    params = {'ch': channel_name}
    
    try:
        response = requests.get(DIYP_BASE_URL, params=params, headers=headers, timeout=10, verify=False)
        if response.status_code == 200:
            # 兼容处理：有些 DIYP 接口返回 JSON，有些返回纯文本
            # 我们假设它返回标准的 DIYP JSON 格式：{"channel": "CCTV1", "date": "2026-06-17", "epg_data": [{"start": "06:00", "title": "..."}]}
            data = response.json()
            return channel_name, data
    except:
        pass
    return channel_name, None

def build_xmltv(all_results, output_path):
    """把并发抓取到的各个频道数据，强行拼装成标准 XMLTV 格式"""
    import datetime
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    
    root = ET.Element('tv')
    root.set('generator-info-name', 'IPTV DIYP to XMLTV')
    
    channel_count = 0
    prog_count = 0
    
    for ch_name, epg_json in all_results:
        if not epg_json or 'epg_data' not in epg_json:
            continue
            
        ch_id = ch_name.lower().replace(" ", "")
        
        # 1. 写入 channel 节点
        channel_node = ET.SubElement(root, 'channel', id=ch_id)
        display_name_node = ET.SubElement(channel_node, 'display-name')
        display_name_node.text = ch_name
        channel_count += 1
        
        # 2. 写入 programme 节点
        epg_list = epg_json.get('epg_data', [])
        for idx, item in enumerate(epg_list):
            start_time_short = item.get('start', '')  # 例如 "06:00"
            title = item.get('title', '')
            
            if not start_time_short or not title:
                continue
                
            # 将 "06:00" 转换为 XMLTV 标准的 "20260617060000 +0800"
            time_clean = start_time_short.replace(":", "")
            start_xmltime = f"{today_str}{time_clean}00 +0800"
            
            # 计算结束时间（如果没有结束时间，默认让它播1小时，或者等于下一个节目的开始时间）
            if idx < len(epg_list) - 1:
                next_time_clean = epg_list[idx+1].get('start', '').replace(":", "")
                stop_xmltime = f"{today_str}{next_time_clean}00 +0800"
            else:
                stop_xmltime = f"{today_str}235959 +0800"
                
            prog_node = ET.SubElement(root, 'programme', start=start_xmltime, stop=stop_xmltime, channel=ch_id)
            title_node = ET.SubElement(prog_node, 'title')
            title_node.text = title
            prog_count += 1

    print(f"\n🎉 转换完成！共生成了 {channel_count} 个频道的 {prog_count} 条节目详情。")
    
    try:
        tree = ET.ElementTree(root)
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"💾 专属节目单已成功写入: {output_path}")
        return True
    except Exception as e:
        print(f"❌ 写入 XML 失败: {e}")
        return False

if __name__ == "__main__":
    # 获取 M3U 里的 573 个频道
    my_channels = get_channels_from_m3u(M3U_URL)
    print(f"📋 从你的直播源中解析出 {len(my_channels)} 个频道。")
    
    if not my_channels:
        print("❌ 未获取到任何有效频道，退出。")
        sys.exit(1)
        
    print(f"⏳ 正在启动多线程并发机制请求 DIYP 接口...")
    final_results = []
    
    # 启动 20 个线程同时并发向 51zmt 接口开火，防止串行过慢
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_single_channel_epg, ch): ch for ch in my_channels}
        for idx, future in enumerate(as_completed(futures), 1):
            ch_name, res_data = future.result()
            if res_data:
                final_results.append((ch_name, res_data))
            if idx % 50 == 0:
                print(f"   已完成 {idx}/{len(my_channels)} 个频道的动态查询...")
                
    # 拼装生成标准的 XML 文件
    success = build_xmltv(final_results, OUTPUT_FILE)
    
    if not success:
        sys.exit(1)
