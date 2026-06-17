import xml.etree.ElementTree as ET
import requests

# ==================== 配置区域 ====================
# 你的 IPTV JSON 订阅地址
JSON_URL = "http://tv.wikiapp.uk:5173/api/subscription/json?token=tok_8K9RBFIE"
# 庞大的全量 XMLTV 源地址（请替换为你自己的大 XML 链接）
BIG_XML_URL = "https://epg.pw/xmltv/epg.xml" 
# 生成的精简版文件名
OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_json(url):
    """从你的 JSON 接口中提取所有频道名称"""
    channels = set()
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        
        # 兼容常见的 IPTV JSON 格式（通常是一个列表，或者包含在某个 list 键中）
        # 自动遍历 JSON 寻找包含频道名字的字段
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    items = value
                    break
        
        for item in items:
            if isinstance(item, dict):
                # 尝试抓取常见的频道名字段
                name = item.get('name') or item.get('title') or item.get('channel_name')
                if name:
                    channels.add(str(name).strip())
                    # 清理常见杂质（例如：[1080p]、HD等），增加匹配率
                    clean_name = name.replace("HD", "").replace("FHD", "").replace("超清", "").replace("高清", "").strip()
                    channels.add(clean_name)
    except Exception as e:
        print(f"❌ 读取 JSON 接口失败: {e}")
    return channels

def filter_xmltv(xml_url, valid_channels, output_path):
    """下载并过滤 XMLTV 文件"""
    print("⏳ 正在下载并解析大型 XMLTV 文件，请稍候...")
    try:
        response = requests.get(xml_url, timeout=60, stream=True)
        tree = ET.parse(response.raw)
        root = tree.getroot()
        
        channels_to_remove = []
        keep_channel_ids = set()
        
        # 1. 过滤 channel 节点
        for channel in root.findall('channel'):
            channel_id = channel.get('id')
            display_names = [name.text.strip() for name in channel.findall('display-name') if name.text]
            
            match = False
            # 只要大 XML 里的 ID 或任意一个显示名称在你的 JSON 频道列表里，就保留
            if channel_id in valid_channels:
                match = True
            else:
                for name in display_names:
                    if name in valid_channels:
                        match = True
                        break
            
            if match:
                keep_channel_ids.add(channel_id)
            else:
                channels_to_remove.append(channel)
                
        for channel in channels_to_remove:
            root.remove(channel)
            
        # 2. 过滤 programme 节点
        programmes_to_remove = []
        for programme in root.findall('programme'):
            prog_channel = programme.get('channel')
            if prog_channel not in keep_channel_ids:
                programmes_to_remove.append(programme)
                
        for programme in programmes_to_remove:
            root.remove(programme)
            
        # 3. 保存新文件
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"🎉 过滤完成！成功保留了 {len(keep_channel_ids)} 个频道的节目单。")
        
    except Exception as e:
        print(f"❌ 过滤 XMLTV 失败: {e}")

if __name__ == "__main__":
    my_channels = get_channels_from_json(JSON_URL)
    print(f"📋 从你的接口中一共解析出 {len(my_channels)} 个频道关键词。")
    
    if my_channels:
        filter_xmltv(BIG_XML_URL, my_channels, OUTPUT_FILE)
    else:
        print("❌ 未获取到任何有效的频道，停止过滤。")