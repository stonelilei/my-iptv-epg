import xml.etree.ElementTree as ET
import requests
import sys

# ==================== 配置区域 ====================
# 1. 你的 IPTV JSON 订阅地址
JSON_URL = "http://tv.wikiapp.uk:5173/api/subscription/json?token=tok_8K9RBFIE"

# 2. 全量 XMLTV 源地址列表 (支持添加任意多个，程序会按顺序依次抓取并融合)
BIG_XML_URLS = [
    "https://epg.112114.xyz/pp.xml",       # 源 A（示例：112114源）
    "https://epg.51zmt.top:444/e.xml",     # 源 B（示例：51zmt源，可根据需求自行修改或增加）
    "https://epg.pw/xmltv/epg_HK.xml",     
    "https://epg.pw/xmltv/epg_TW.xml",
    "https://epg.pw/xmltv/epg_US.xml",
    # "https://xxx/third_pool.xml",        # 源 C（如果还有，取消注释并在这里继续加）
]

# 3. 生成的精简版文件名
OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_json(url):
    """从你的 JSON 接口中提取所有频道名称"""
    channels = set()
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        data = response.json()
        
        print(f"[DEBUG] 接口返回数据类型: {type(data)}")
        
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
                    name_str = str(name).strip()
                    channels.add(name_str)
                    # 清理常见杂质，提高匹配度
                    clean_name = name_str.replace("HD", "").replace("FHD", "").replace("超清", "").replace("高清", "").strip()
                    channels.add(clean_name)
                    
    except Exception as e:
        print(f"❌ 读取 JSON 接口失败: {e}")
    return channels

def merge_and_filter_epg(xml_urls, valid_channels, output_path):
    """遍历多个 XMLTV 源，提取匹配的频道和节目，最终融合成一个新文件"""
    
    # 创建一个全新的 XMLTV 根节点结构
    new_root = ET.Element('tv')
    new_root.set('generator-info-name', 'IPTV EPG Merger')
    
    # 用于记录已经添加过的 channel id 和 programme，防止多源融合时产生完全重复的数据
    added_channel_ids = set()
    added_programmes = set()
    
    total_matched_channels = 0

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    # 循环读取每一个 EPG 源
    for index, url in enumerate(xml_urls, 1):
        print(f"\n⏳ [{index}/{len(xml_urls)}] 正在下载并解析源: {url}")
        try:
            # 提高超时时间到 120 秒，防止大文件下载超时
            response = requests.get(url, headers=headers, timeout=120, stream=True)
            
            if response.status_code != 200:
                print(f"⚠️ 下载失败，HTTP 状态码: {response.status_code}，跳过此源。")
                continue
                
            tree = ET.parse(response.raw)
            root = tree.getroot()
            
            keep_channel_ids_this_source = set()
            
            # 1. 处理当前源的 channel 节点
            for channel in root.findall('channel'):
                channel_id = channel.get('id')
                display_names = [name.text.strip() for name in channel.findall('display-name') if name.text]
                
                match = False
                if channel_id in valid_channels:
                    match = True
                else:
                    for name in display_names:
                        if name in valid_channels:
                            match = True
                            break
                
                if match:
                    keep_channel_ids_this_source.add(channel_id)
                    # 如果这个频道 ID 在之前的源里没添加过，就加到新 XML 中
                    if channel_id not in added_channel_ids:
                        new_root.append(channel)
                        added_channel_ids.add(channel_id)
            
            source_match_count = len(keep_channel_ids_this_source)
            total_matched_channels += source_match_count
            print(f"✅ 该源成功匹配到 {source_match_count} 个您的直播频道。")
            
            # 2. 处理当前源的 programme 节点
            prog_count = 0
            for programme in root.findall('programme'):
                prog_channel = programme.get('channel')
                # 只有属于匹配成功频道的节目才保留
                if prog_channel in keep_channel_ids_this_source:
                    start = programme.get('start')
                    title_node = programme.find('title')
                    title_text = title_node.text if title_node is not None else ""
                    
                    # 建立一个唯一的节目特征标识（频道+开始时间+标题），防止多源重合时堆积重复节目
                    prog_fingerprint = f"{prog_channel}_{start}_{title_text}"
                    
                    if prog_fingerprint not in added_programmes:
                        new_root.append(programme)
                        added_programmes.add(prog_fingerprint)
                        prog_count += 1
            
            print(f"🎬 从该源成功合并了 {prog_count} 条节目单详情。")
            
        except Exception as e:
            print(f"❌ 解析此源时发生错误: {e}，已跳过。")
            continue

    # 检查最终是否有数据
    if len(added_channel_ids) == 0:
        print("\n⚠️ 警告：在所有配置的 EPG 源中，均未匹配到您订阅里的任何频道！")
    else:
        print(f"\n🎉 融合完成！共去重保留了 {len(added_channel_ids)} 个频道和 {len(added_programmes)} 条节目。")

    # 3. 统一写入新文件
    try:
        new_tree = ET.ElementTree(new_root)
        new_tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"💾 精简版多源融合节目单已成功写入: {output_path}")
        return True
    except Exception as e:
        print(f"❌ 写入新 XML 文件失败: {e}")
        return False

if __name__ == "__main__":
    # 从你的接口获取频道
    my_channels = get_channels_from_json(JSON_URL)
    print(f"📋 从你的接口中一共解析出 {len(my_channels)} 个频道关键词。")
    
    success = False
    if my_channels:
        # 调用融合多源函数
        success = merge_and_filter_epg(BIG_XML_URLS, my_channels, OUTPUT_FILE)
    else:
        print("❌ 未获取到任何有效的频道，停止过滤。")
        
    if not success:
        sys.exit(1)
