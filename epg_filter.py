import xml.etree.ElementTree as ET
import requests
import sys
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区域 ====================
# 已经确认这是 M3U 文本源
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
    """超级兼容的 M3U/纯文本频道名提取器"""
    channels = set()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=25, verify=False)
        response.encoding = response.apparent_encoding  
        content_text = response.text
        
        # 兜底：如果这依然是个 JSON
        if content_text.strip().startswith('{') or content_text.strip().startswith('['):
            try:
                data = response.json()
                items = data if isinstance(data, list) else data.get('data', []) or data.get('channels', [])
                for item in items:
                    if isinstance(item, dict):
                        name = item.get('name') or item.get('title') or item.get('channel_name')
                        if name: add_channel_variants(channels, str(name))
                if channels: return channels
            except: pass

        # 核心：高容错解析 M3U 文本流
        lines = content_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith("#EXTINF"):
                # 1. 提取 tvg-name
                tvg_name_match = re.search(r'tvg-name="([^"]+)"', line, re.IGNORECASE)
                if tvg_name_match:
                    add_channel_variants(channels, tvg_name_match.group(1))
                
                # 2. 提取 tvg-id
                tvg_id_match = re.search(r'tvg-id="([^"]+)"', line, re.IGNORECASE)
                if tvg_id_match:
                    add_channel_variants(channels, tvg_id_match.group(1))
                
                # 3. 提取后半截的显示名称（不管有没有逗号，通杀截取）
                if ',' in line:
                    display_name = line.split(',')[-1].strip()
                    # 防止 display_name 里面夹杂特殊分组符号，如 "央视-CCTV1" 提取为 "CCTV1"
                    if display_name:
                        add_channel_variants(channels, display_name)
                        # 如果带减号，额外把减号后面的捞出来
                        if '-' in display_name:
                            add_channel_variants(channels, display_name.split('-')[-1])
            
            # 兼容非标准格式：如果行里面包含中文、CCTV、HBO、卫视等关键字，且不含 http，直接当做频道名抓取
            elif not line.startswith("#") and not line.startswith("http") and len(line) < 30:
                if ',' in line:
                    line = line.split(',')[0]
                add_channel_variants(channels, line)

    except Exception as e:
        print(f"❌ 请求订阅接口时发生致命错误: {e}")
        
    return channels

def add_channel_variants(channel_set, name):
    """清理名称中常见的各种冗余后缀，统一格式注入集合"""
    name_str = name.strip()
    # 过滤掉杂质字符
    if name_str and not name_str.startswith("http") and not name_str.startswith("#"):
        channel_set.add(name_str)
        
        # 移除常见干扰后缀，生成模糊匹配变体
        clean_name = name_str.replace("HD", "").replace("FHD", "").replace("超清", "").replace("高清", "")
        clean_name = clean_name.replace(" ", "").replace("-", "").replace("_", "").lower().strip()
        if clean_name:
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
            
            # 【诊断日志】
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
                
                match = False
                check_list = [channel_id] + display_names
                
                for item in check_list:
                    if not item: continue
                    item_str = str(item).strip()
                    item_fuzzy = item_str.replace(" ", "").replace("-", "").replace("_", "").lower()
                    
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
