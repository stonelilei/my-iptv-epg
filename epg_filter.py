import xml.etree.ElementTree as ET
import requests
import sys
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区域 ====================
JSON_URL = "http://hn.wikiapp.uk:5678/tv.m3u?token=cd52e0986f&url=myiptv"

BIG_XML_URLS = [
    "https://epg.112114.xyz/pp.xml",       
    "https://epg.51zmt.top:444/e.xml",     
    "https://epg.pw/xmltv/epg_HK.xml",     
    "https://epg.pw/xmltv/epg_TW.xml",
    "https://epg.pw/xmltv/epg_US.xml",
]

OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_json(url):
    """自适应解析：优先 JSON，失败则转换为纯文本/M3U 规则提取频道名称"""
    channels = set()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=25, verify=False)
        response.encoding = response.apparent_encoding  
        content_text = response.text
        
        # 尝试方法 1：作为 JSON 解析
        try:
            data = response.json()
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if 'data' in data and isinstance(data['data'], list):
                    items = data['data']
                elif 'channels' in data and isinstance(data['channels'], list):
                    items = data['channels']
                else:
                    for key, value in data.items():
                        if isinstance(value, list):
                            items = value
                            break
            for item in items:
                if isinstance(item, dict):
                    name = item.get('name') or item.get('title') or item.get('channel_name') or item.get('channelName')
                    if name:
                        add_channel_variants(channels, str(name))
            if channels:
                return channels
        except Exception:
            pass

        # 尝试方法 2：降级为纯文本/M3U 解析
        lines = content_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("#EXTINF"):
                tvg_name_match = re.search(r'tvg-name="([^"]+)"', line)
                if tvg_name_match:
                    add_channel_variants(channels, tvg_name_match.group(1))
                
                tvg_id_match = re.search(r'tvg-id="([^"]+)"', line)
                if tvg_id_match:
                    add_channel_variants(channels, tvg_id_match.group(1))
                
                if ',' in line:
                    display_name = line.split(',')[-1].strip()
                    if display_name:
                        add_channel_variants(channels, display_name)
            elif ',' in line and not line.startswith("http"):
                parts = line.split(',')
                if parts[0] and not parts[0].startswith("#"):
                    add_channel_variants(channels, parts[0])

    except Exception as e:
        print(f"❌ 请求订阅接口时发生致命错误: {e}")
        
    return channels

def add_channel_variants(channel_set, name):
    """统一清洗名称并注入集合"""
    name_str = name.strip()
    if name_str and not name_str.startswith("http"):
        channel_set.add(name_str)
        # 增加更多常见的变体清洗逻辑
        clean_name = name_str.replace("HD", "").replace("FHD", "").replace("超清", "").replace("高清", "").replace(" ", "").replace("-", "").lower().strip()
        channel_set.add(clean_name)

def merge_and_filter_epg(xml_urls, valid_channels, output_path):
    new_root = ET.Element('tv')
    new_root.set('generator-info-name', 'IPTV EPG Merger')
    
    added_channel_ids = set()
    added_programmes = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for index, url in enumerate(xml_urls, 1):
        print(f"\n⏳ [{index}/{len(xml_urls)}] 正在下载并解析源: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=120, stream=True, verify=False)
            if response.status_code != 200:
                print(f"⚠️ 下载失败，HTTP 状态码: {response.status_code}")
                continue
                
            tree = ET.parse(response.raw)
            root = tree.getroot()
            keep_channel_ids_this_source = set()
            
            # 【诊断日志】打印大 EPG 源里前 5 个频道的名字，用于肉眼比对
            sample_channels = root.findall('channel')[:5]
            print(f"[🔍 诊断] 该 EPG 源前几个频道的名称格式示例:")
            for sc in sample_channels:
                sc_id = sc.get('id')
                sc_names = [n.text for n in sc.findall('display-name') if n.text]
                print(f"    -> ID: '{sc_id}', 显示名: {sc_names}")
            
            # 1. 过滤 channel
            for channel in root.findall('channel'):
                channel_id = channel.get('id')
                display_names = [name.text.strip() for name in channel.findall('display-name') if name.text]
                
                # 增强匹配：同时做全小写、去空格、去减号的模糊匹配
                match = False
                
                # 构建用于模糊匹配的检测序列
                check_list = [channel_id] + display_names
                
                for item in check_list:
                    if not item: continue
                    item_str = str(item).strip()
                    item_fuzzy = item_str.replace(" ", "").replace("-", "").lower()
                    
                    if item_str in valid_channels or item_fuzzy in valid_channels:
                        match = True
                        break
                
                if match:
                    keep_channel_ids_this_source.add(channel_id)
                    if channel_id not in added_channel_ids:
                        new_root.append(channel)
                        added_channel_ids.add(channel_id)
            
            source_match_count = len(keep_channel_ids_this_source)
            print(f"✅ 该源成功匹配到 {source_match_count} 个您的直播频道。")
            
            # 2. 过滤 programme
            prog_count = 0
            for programme in root.findall('programme'):
                prog_channel = programme.get('channel')
                if prog_channel in keep_channel_ids_this_source:
                    start = programme.get('start')
                    title_node = programme.find('title')
                    title_text = title_node.text if title_node is not None else ""
                    
                    prog_fingerprint = f"{prog_channel}_{start}_{title_text}"
                    if prog_fingerprint not in added_programmes:
                        new_root.append(programme)
                        added_programmes.add(prog_fingerprint)
                        prog_count += 1
            print(f"🎬 从该源成功合并了 {prog_count} 条节目单详情。")
            
        except Exception as e:
            print(f"❌ 解析此源时发生错误: {e}")
            continue

    if len(added_channel_ids) == 0:
        print("\n⚠️ 警告：在所有配置的 EPG 源中，均未匹配到您订阅里的任何频道！")
    else:
        print(f"\n🎉 融合完成！共去重保留了 {len(added_channel_ids)} 个频道和 {len(added_programmes)} 条节目。")

    try:
        new_tree = ET.ElementTree(new_root)
        new_tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"💾 精简版多源融合节目单已成功写入: {output_path}")
        return True
    except Exception as e:
        print(f"❌ 写入新 XML 文件失败: {e}")
        return False

if __name__ == "__main__":
    my_channels = get_channels_from_json(JSON_URL)
    
    # 【诊断日志】打印你的直播源里抓出来的前 10 个名字
    print(f"📋 从你的接口中一共解析出 {len(my_channels)} 个频道关键词。")
    print(f"[🔍 诊断] 你的直播源频道名称前 10 个示例:")
    for idx, ch in enumerate(list(my_channels)[:10]):
        print(f"    {idx+1}. '{ch}'")
        
    success = False
    if my_channels:
        success = merge_and_filter_epg(BIG_XML_URLS, my_channels, OUTPUT_FILE)
    else:
        print("❌ 未获取到任何有效的频道，停止过滤。")
        
    if not success:
        sys.exit(1)
