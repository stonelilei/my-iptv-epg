import xml.etree.ElementTree as ET
import requests
import sys
import re
import urllib3
import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区域 ====================
# 1. 你的 IPTV 直播源地址
M3U_URL = "http://hn.wikiapp.uk:5678/tv.m3u?token=cd52e0986f&url=myiptv"

# 2. 生成的精简版文件名
OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_m3u(url):
    """从 M3U 中提取最干净的频道原始显示名称"""
    channels = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=25, verify=False)
        response.encoding = response.apparent_encoding  
        lines = response.text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                if ',' in line:
                    display_name = line.split(',')[-1].strip()
                    if display_name and not display_name.startswith("#"):
                        # 清理掉名字中的特殊小尾巴，只保留纯频道名以便在网上搜索
                        clean_name = re.sub(r'\[.*?\]|\(.*?\)|HD|FHD|高清|超清', '', display_name).strip()
                        if clean_name:
                            channels.add(clean_name)
    except Exception as e:
        print(f"❌ 请求 M3U 直播源失败: {e}")
    return channels

def fetch_epg_from_web(channel_name):
    """核心网络爬虫：直接去主流电视指南网站搜索并抓取当前频道的节目单"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.tvsou.com/'
    }
    
    epg_data = []
    try:
        # 第一步：拿着频道名去网站的搜索接口，寻找该频道的专属页面 ID
        search_url = f"https://www.tvsou.com/search/?q={channel_name}"
        search_res = requests.get(search_url, headers=headers, timeout=12, verify=False)
        search_res.encoding = 'utf-8'
        
        # 从搜索结果中提取真实的频道详情页链接（形如 /epg/cctv1/ 或 /epg/hunan_weishi/）
        channel_path_match = re.search(r'href="(/epg/[a-zA-Z0-9_-]+/)"', search_res.text)
        if not channel_path_match:
            # 尝试第二种备用搜索匹配结构
            channel_path_match = re.search(r'/epg/\w+-\w+/', search_res.text)
            
        if channel_path_match:
            channel_path = channel_path_match.group(1)
            target_url = f"https://www.tvsou.com{channel_path}"
            
            # 第二步：直接请求该频道的具体节目单网页
            page_res = requests.get(target_url, headers=headers, timeout=12, verify=False)
            page_res.encoding = 'utf-8'
            
            # 第三步：使用 BeautifulSoup 提取网页里的时间表和节目名
            soup = BeautifulSoup(page_res.text, 'html.parser')
            
            # 适配该网站标准的节目列表标签结构
            prog_items = soup.find_all('li', class_='g_li') or soup.find_all('tr', class_='prog_tr')
            
            if not prog_items:
                # 兜底：用正则表达式直接从网页源代码里抽取时间（00:00-23:59）和对应的节目名
                matches = re.findall(r'(\d{2}:\d{2}).*?title="([^"]+)"', page_res.text)
                for time_str, title_str in matches:
                    if len(title_str) < 50:  # 过滤掉过长的 HTML 干扰文本
                        epg_data.append({'time': time_str, 'title': title_str})
            else:
                for item in prog_items:
                    time_node = item.find(class_='time') or item.find('span')
                    title_node = item.find(class_='title') or item.find('a')
                    if time_node and title_node:
                        time_str = time_node.text.strip()
                        title_str = title_node.text.strip()
                        if re.match(r'\d{2}:\d{2}', time_str):
                            epg_data.append({'time': time_str, 'title': title_str})
                            
            if epg_data:
                # 对抓取到的结果按时间排个序，确保拼装时不紊乱
                epg_data = sorted(epg_data, key=lambda x: x['time'])
                return channel_name, epg_data
    except:
        pass
    return channel_name, None

def build_xmltv_from_scratch(all_results, output_path):
    """根据实时爬取上来的多线程结果，原地组装纯正的 XMLTV 格式"""
    today_str = datetime.datetime.now().strftime("%Y%m%d")
    
    root = ET.Element('tv')
    root.set('generator-info-name', 'IPTV Pure Web Scraper')
    
    channel_count = 0
    prog_count = 0
    
    for ch_name, epg_list in all_results:
        if not epg_list:
            continue
            
        ch_id = ch_name.lower().replace(" ", "").replace("-", "")
        
        # 1. 创建频道声明节点
        channel_node = ET.SubElement(root, 'channel', id=ch_id)
        display_name_node = ET.SubElement(channel_node, 'display-name')
        display_name_node.text = ch_name
        channel_count += 1
        
        # 2. 循环拼接各个时间段的节目预告详情
        for idx, item in enumerate(epg_list):
            time_short = item.get('time', '').replace(":", "")  # "0800"
            title = item.get('title', '')
            
            if not time_short or not title:
                continue
                
            start_xmltime = f"{today_str}{time_short}00 +0800"
            
            # 计算节目结束时间：默认为下一个节目的开始时间，最后一个播放到深夜
            if idx < len(epg_list) - 1:
                next_time_short = epg_list[idx+1].get('time', '').replace(":", "")
                stop_xmltime = f"{today_str}{next_time_short}00 +0800"
            else:
                stop_xmltime = f"{today_str}235959 +0800"
                
            prog_node = ET.SubElement(root, 'programme', start=start_xmltime, stop=stop_xmltime, channel=ch_id)
            title_node = ET.SubElement(prog_node, 'title')
            title_node.text = title
            prog_count += 1

    print(f"\n🎉 互联网实时爬取完成！共抓取了 {channel_count} 个频道的 {prog_count} 条最新节目表。")
    
    try:
        new_tree = ET.ElementTree(root)
        new_tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"💾 你的纯自主订阅地址已就绪，成功写入: {output_path}")
        return True
    except Exception as e:
        print(f"❌ 写入 XML 失败: {e}")
        return False

if __name__ == "__main__":
    # 解析直播源
    my_channels = get_channels_from_m3u(M3U_URL)
    print(f"📋 从你的直播源中成功提取出 {len(my_channels)} 个待抓取的独立频道。")
    
    if not my_channels:
        print("❌ 频道列表为空，停止运行。")
        sys.exit(1)
        
    print("🚀 正在激活全网分布式多线程爬虫，开始实时向互联网检索节目单...")
    final_results = []
    
    # 开启 25 路线程并发对目标网站发起高速检索
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(fetch_epg_from_web, ch): ch for ch in my_channels}
        for idx, future in enumerate(as_completed(futures), 1):
            ch_name, web_data = future.result()
            if web_data:
                final_results.append((ch_name, web_data))
            if idx % 50 == 0:
                print(f"   进度报告：已完成全网检索 {idx}/{len(my_channels)} 个频道...")
                
    # 拼装生成文件
    success = build_xmltv_from_scratch(final_results, OUTPUT_FILE)
    
    if not success:
        sys.exit(1)
