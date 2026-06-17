import xml.etree.ElementTree as ET
import requests
import sys
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 配置区域 ====================
# 1. 你的 IPTV 直播源地址
M3U_URL = "http://hn.wikiapp.uk:5678/tv.m3u?token=cd52e0986f&url=myiptv"

# 2. 全量稳定且对海外CDN极其友好的大节目单源（112114 主线+地方精简综合源）
# 该源在海外下载极快，且格式极其规范，不易挂掉
BIG_XML_URL = "https://epg.112114.xyz/pp.xml"

# 3. 生成的精简版文件名
OUTPUT_FILE = "my_epg.xml"
# ==================================================

def get_channels_from_m3u(url):
    """自适应提取 M3U 频道，深度清洗并建立核心匹配库"""
    channels = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=25, verify=False)
        response.encoding = response.apparent_encoding  
        lines = response.text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                # 1. 捞取 tvg-name / tvg-id
                tvg_name = re.search(r'tvg-name="([^"]+)"', line, re.IGNORECASE)
                tvg_id = re.search(r'tvg-id="([^"]+)"', line, re.IGNORECASE)
                if tvg_name: add_to_set(channels, tvg_name.group(1))
                if tvg_id: add_to_set(channels, tvg_id.group(1))
                
                # 2. 捞取逗号后的标准名字
                if ',' in line:
                    display_name = line.split(',')[-1].strip()
                    if display_name and not display_name.startswith("#"):
                        add_to_set(channels, display_name)
    except Exception as e:
        print(f"❌ 请求 M3U 直播源失败: {e}")
    return channels

def add_to_set(channel_set, name):
    """把频道名及其规范化变体加入集合，最大化提高配对概率"""
    name_str = name.strip()
    if name_str and not name_str.startswith("http"):
        channel_set.add(name_str)
        # 移除常见小尾巴：HD, FHD, 高清, 超清
        clean = re.sub(r'\[.*?\]|\(.*?\)|HD|FHD|高清|超清', '', name_str).strip()
        channel_set.add(clean)
        # 纯数字/字母变体（例如：把 CCTV-1 综合 降维成 cctv1）
        fuzzy = clean.replace(" ", "").replace("-", "").replace("_", "").replace("频道", "").lower()
        if fuzzy:
            channel_set.add(fuzzy)

def get_smart_alias(name_str):
    """核心别名翻译器：当名字不规范时，强行翻译成112114大节目单里标准的channel id"""
    name_fuzzy = name_str.replace(" ", "").replace("-", "").replace("_", "").replace("频道", "").lower()
    
    # 常规央视别名自动对齐字典
    alias_dict = {
        "cctv1": "cctv1", "cctv1综合": "cctv1", "中央1": "cctv1", "中央一": "cctv1",
        "cctv2": "cctv2", "cctv2财经": "cctv2",
        "cctv3": "cctv3", "cctv3综艺": "cctv3",
        "cctv4": "cctv4", "cctv4中文国际": "cctv4",
        "cctv5": "cctv5", "cctv5体育": "cctv5",
        "cctv6": "cctv6", "cctv6电影": "cctv6",
        "cctv7": "cctv7", "cctv7国防军事": "cctv7", "cctv7军事": "cctv7",
        "cctv8": "cctv8", "cctv8电视剧": "cctv8",
        "cctv9": "cctv9", "cctv9记录": "cctv9", "cctv9纪录": "cctv9",
        "cctv10": "cctv10", "cctv10科教": "cctv10",
        "cctv11": "cctv11", "cctv11戏曲": "cctv11",
        "cctv12": "cctv12", "cctv12社会与法": "cctv12",
        "cctv13": "cctv13", "cctv13新闻": "cctv13",
        "cctv14": "cctv14", "cctv14少儿": "cctv14",
        "cctv15": "cctv15", "cctv15音乐": "cctv15",
        "cctv16": "cctv16", "cctv16奥林匹克": "cctv16",
        "cctv17": "cctv17", "cctv17农业农村": "cctv17",
    }
    return alias_dict.get(name_fuzzy, name_fuzzy)

def do_filter(xml_url, valid_channels, output_path):
    """流式下载并高强容错过滤 EPG 源"""
    new_root = ET.Element('tv')
    new_root.set('generator-info-name', 'IPTV EPG Smart Filter')
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    print(f"⏳ 正在拉取远端核心节目单: {xml_url}")
    try:
        response = requests.get(xml_url, headers=headers, timeout=45, stream=True, verify=False)
        if response.status_code != 200:
            print(f"❌ 下载主节目单失败，状态码: {response.status_code}")
            return False
            
        tree = ET.parse(response.raw)
        root = tree.getroot()
        
        keep_channel_ids = set()
        
        # 1. 过滤并保存合规的 channel 节点
        for channel in root.findall('channel'):
            channel_id = channel.get('id')
            display_names = [n.text.strip() for n in channel.findall('display-name') if n.text]
            
            # 将大源的名字全部拉出来做别名清洗
            match = False
            check_list = [channel_id] + display_names
            
            for item in check_list:
                if not item: continue
                item_raw = str(item).strip()
                item_fuzzy = item_raw.replace(" ", "").replace("-", "").replace("_", "").replace("频道", "").lower()
                
                # 双重判定：字面绝对匹配，或者智能别名对齐匹配
                if (item_raw in valid_channels or 
                    item_fuzzy in valid_channels or 
                    get_smart_alias(item_raw) in valid_channels):
                    match = True
                    break
                    
            if match:
                keep_channel_ids.add(channel_id)
                new_root.append(channel)
                
        print(f"✅ 成功从大源中强行对齐了 {len(keep_channel_ids)} 个您的直播频道。")
        
        # 2. 过滤并拉取 programme 节点
        prog_count = 0
        for programme in root.findall('programme'):
            prog_channel = programme.get('channel')
            if prog_channel in keep_channel_ids:
                new_root.append(programme)
                prog_count += 1
                
        print(f"🎬 成功灌入 {prog_count} 条精确到小时的节目单详情。")
        
        # 3. 强行输出文件
        new_tree = ET.ElementTree(new_root)
        new_tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"💾 精简版节目单已安全落盘: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ 过滤处理期间发生异常: {e}")
        return False

if __name__ == "__main__":
    my_channels = get_channels_from_m3u(M3U_URL)
    print(f"📋 直播源中已成功提取 {len(my_channels)} 个特征识别码。")
    
    if my_channels:
        success = do_filter(BIG_XML_URL, my_channels, OUTPUT_FILE)
        if not success:
            sys.exit(1)
    else:
        print("❌ 未在你的 M3U 中捞出任何可用频道，停止运行。")
        sys.exit(1)
