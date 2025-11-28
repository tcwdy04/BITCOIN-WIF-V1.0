import base58
import time
import os
import json
import signal
import sys
import torch
import numpy as np
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import hashlib
import multiprocessing as mp
from typing import List, Tuple, Generator
import random
import secrets
import socket
import requests
from datetime import datetime

# ================== 配置区域 ==================

# 主节点配置
MASTER_NODE = "192.168.2.3"  # 主节点IP
MASTER_PORT = 8888

# 本地配置
BATCH_SIZE = 1000000
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
NUM_WORKERS = min(8, mp.cpu_count())
NODE_ID = socket.gethostname()


# 颜色配置
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


# ================== 分布式管理器 ==================

class DistributedManager:
    """分布式计算管理器"""

    def __init__(self, master_host=MASTER_NODE, master_port=MASTER_PORT):
        self.master_host = master_host
        self.master_port = master_port
        self.node_id = NODE_ID
        self.config = None
        self.connected = False

    def load_config_from_master(self):
        """从主节点加载配置"""
        try:
            print(f"{Colors.CYAN}🔗 正在连接主节点 {self.master_host}:{self.master_port}...{Colors.END}")
            response = requests.get(f"http://{self.master_host}:{self.master_port}/config", timeout=10)
            if response.status_code == 200:
                self.config = response.json()
                self.connected = True
                print(f"{Colors.GREEN}✅ 成功连接到主节点!{Colors.END}")
                print(f"{Colors.CYAN}📋 节点配置:{Colors.END}")
                print(f"  {Colors.WHITE}• 节点ID:{Colors.END} {Colors.BOLD}{self.config['node_id']}{Colors.END}")
                print(
                    f"  {Colors.WHITE}• 搜索策略:{Colors.END} {Colors.BOLD}{self.config['search_strategy']['mode']}{Colors.END}")
                print(
                    f"  {Colors.WHITE}• 分区种子:{Colors.END} {Colors.BOLD}{self.config['base_seed'][:16]}...{Colors.END}")
                print(f"  {Colors.WHITE}• 批次大小:{Colors.END} {Colors.BOLD}{self.config['batch_size']:,}{Colors.END}")
                print(
                    f"  {Colors.WHITE}• 搜索空间:{Colors.END} {Colors.BOLD}{self.config['search_space_info']['description']}{Colors.END}")
                return True
            else:
                print(f"{Colors.RED}❌ 主节点响应异常: {response.status_code}{Colors.END}")
                return False
        except Exception as e:
            print(f"{Colors.RED}❌ 无法连接到主节点: {e}{Colors.END}")
            return False

    def report_progress(self, tested_count: int, found_count: int):
        """向主节点报告进度，带重试机制"""
        if not self.connected or not self.config:
            return False

        max_retries = 3
        for attempt in range(max_retries):
            try:
                data = {
                    'node_id': self.config['node_id'],
                    'tested_count': tested_count,
                    'found_count': found_count,
                    'partition_seed': self.config.get('base_seed', 'unknown')
                }

                response = requests.post(
                    f"http://{self.master_host}:{self.master_port}/progress",
                    json=data,
                    timeout=30  # 增加超时时间
                )

                if response.status_code == 200:
                    return True
                else:
                    print(f"{Colors.RED}❌ 进度报告失败: HTTP {response.status_code}{Colors.END}")

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"{Colors.YELLOW}⏰ 请求超时，重试中... ({attempt + 1}/{max_retries}){Colors.END}")
                    time.sleep(5)
                continue
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    print(f"{Colors.RED}🔌 连接错误，重试中... ({attempt + 1}/{max_retries}){Colors.END}")
                    time.sleep(5)
                continue
            except Exception as e:
                print(f"{Colors.RED}❌ 报告进度错误: {e}{Colors.END}")
                break

        print(f"{Colors.RED}🚫 进度报告失败，转为独立运行模式{Colors.END}")
        self.connected = False
        return False

    def report_found_wif(self, wif_data: dict):
        """向主节点报告找到的WIF"""
        if not self.connected or not self.config:
            return False

        try:
            data = {
                'wif': wif_data['wif'],
                'private_key': wif_data['private_key'],
                'compressed': wif_data['compressed'],
                'node_id': self.config['node_id'],
                'found_count': wif_data['found_count']
            }
            response = requests.post(
                f"http://{self.master_host}:{self.master_port}/found_wif",
                json=data,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            print(f"{Colors.YELLOW}⚠️  报告WIF到主节点失败: {e}{Colors.END}")
            return False


# ================== 自适应搜索管理器 ==================

class AdaptiveSearchManager:
    """自适应搜索管理器"""

    def __init__(self, template, position_candidates, base_seed, clues, total_nodes, node_index, search_strategy,
                 search_space_info):
        self.template = template
        self.position_candidates = position_candidates
        self.base_seed = base_seed
        self.clues = clues
        self.total_nodes = total_nodes
        self.node_index = node_index
        self.search_strategy = search_strategy
        self.search_space_info = search_space_info

        self.variable_indices = self._get_variable_indices()

        # 时间控制
        self.rotation_interval_hours = search_strategy.get('rotation_interval_hours', 24)
        self.current_seed_start_time = time.time()
        self.generation_count = 0
        self.rotation_count = 0

        # 根据策略初始化
        self.search_mode = search_strategy['mode']
        self._initialize_search()

        print(f"{Colors.CYAN}🎯 自适应搜索策略: {self.search_mode}{Colors.END}")
        print(f"  {Colors.WHITE}• 描述:{Colors.END} {search_strategy['description']}")

    def _get_variable_indices(self):
        """获取可变位置索引"""
        indices = []
        for pos_str in self.position_candidates.keys():
            try:
                pos_int = int(pos_str) - 1  # 位置1对应索引0
                if 0 <= pos_int < len(self.template):
                    indices.append(pos_int)
            except ValueError:
                continue
        return indices

    def _initialize_search(self):
        """初始化搜索"""
        if self.search_mode == "sequential_partitioned":
            self._init_sequential_search()
        elif self.search_mode == "random_with_memory":
            self._init_random_with_memory()
        else:  # partitioned_random_rotating
            self._init_rotating_random()

    def _init_sequential_search(self):
        """初始化顺序搜索"""
        total_combinations = self.search_space_info['total_combinations']
        combinations_per_node = total_combinations // self.total_nodes

        self.start_index = self.node_index * combinations_per_node
        self.end_index = self.start_index + combinations_per_node

        if self.node_index == self.total_nodes - 1:  # 最后一个节点处理剩余部分
            self.end_index = total_combinations

        self.current_index = self.start_index

        print(f"{Colors.GREEN}🔍 顺序分区搜索初始化{Colors.END}")
        print(f"  {Colors.WHITE}• 分配范围:{Colors.END} {self.start_index:,} - {self.end_index:,}")
        print(f"  {Colors.WHITE}• 组合数量:{Colors.END} {self.end_index - self.start_index:,}")
        print(f"  {Colors.WHITE}• 总组合数:{Colors.END} {total_combinations:,}")

    def _init_random_with_memory(self):
        """初始化记忆随机搜索"""
        self.tested_combinations = set()
        self.memory_size = self.search_strategy.get('memory_size', 1000000)

        # 初始化随机数生成器
        seed_int = int(self.base_seed[:16], 16) if len(self.base_seed) >= 16 else hash(self.base_seed)
        random.seed(seed_int)

        print(f"{Colors.BLUE}🎲 记忆随机搜索初始化{Colors.END}")
        print(f"  {Colors.WHITE}• 记忆大小:{Colors.END} {self.memory_size:,}")
        print(f"  {Colors.WHITE}• 初始种子:{Colors.END} {self.base_seed[:16]}...")

    def _init_rotating_random(self):
        """初始化轮换随机搜索"""
        self.current_seed = self.base_seed
        self.tested_combinations = set()
        self.attempts_since_last_found = 0
        self.rotation_count = 0

        print(f"{Colors.MAGENTA}🔄 轮换随机搜索初始化{Colors.END}")
        print(f"  {Colors.WHITE}• 轮换间隔:{Colors.END} {self.rotation_interval_hours}小时")
        print(f"  {Colors.WHITE}• 初始种子:{Colors.END} {self.current_seed[:16]}...")
        print(
            f"  {Colors.WHITE}• 无结果限制:{Colors.END} {self.search_strategy.get('max_attempts_no_result', 100000000):,}")

    def _generate_rotating_seed(self, rotation_count):
        """生成轮换种子"""
        seed_data = f"{self.base_seed}_{self.node_index}_{rotation_count}_{time.time()}"
        return hashlib.sha256(seed_data.encode()).hexdigest()

    def _should_rotate_seed(self):
        """判断是否应该更换种子"""
        current_time = time.time()
        elapsed_hours = (current_time - self.current_seed_start_time) / 3600

        # 条件1: 超过轮换间隔
        if elapsed_hours >= self.rotation_interval_hours:
            return True, f"时间轮换 ({elapsed_hours:.1f}小时)"

        # 条件2: 长时间无结果
        max_attempts = self.search_strategy.get('max_attempts_no_result', 100000000)
        if self.attempts_since_last_found > max_attempts:
            return True, f"无结果轮换 ({self.attempts_since_last_found:,}次尝试)"

        return False, ""

    def _rotate_seed_if_needed(self):
        """如果需要则更换种子"""
        should_rotate, reason = self._should_rotate_seed()

        if should_rotate:
            self.rotation_count += 1
            old_seed = self.current_seed

            self.current_seed = self._generate_rotating_seed(self.rotation_count)
            self.current_seed_start_time = time.time()
            self.tested_combinations.clear()
            self.attempts_since_last_found = 0

            print(f"{Colors.YELLOW}🔄 种子轮换 #{self.rotation_count} - {reason}{Colors.END}")
            print(f"  {Colors.WHITE}旧种子:{Colors.END} {old_seed[:16]}...")
            print(f"  {Colors.WHITE}新种子:{Colors.END} {self.current_seed[:16]}...")

            return True
        return False

    def generate_batch(self, batch_size=1000000):
        """生成候选批次"""
        if self.search_mode == "sequential_partitioned":
            return self._generate_sequential_batch(batch_size)
        elif self.search_mode == "random_with_memory":
            return self._generate_memory_random_batch(batch_size)
        else:  # partitioned_random_rotating
            return self._generate_rotating_random_batch(batch_size)

    def _generate_sequential_batch(self, batch_size):
        """生成顺序批次"""
        batch = []

        while len(batch) < batch_size and self.current_index < self.end_index:
            candidate = self._index_to_candidate(self.current_index)
            if self._satisfies_clues(candidate):
                batch.append(candidate)
            self.current_index += 1

        # 检查是否完成
        if self.current_index >= self.end_index:
            if batch:  # 返回最后一批
                return batch
            else:
                print(f"{Colors.GREEN}✅ 本节点顺序搜索任务完成!{Colors.END}")
                return []

        return batch

    def _generate_memory_random_batch(self, batch_size):
        """生成记忆随机批次"""
        batch = []
        attempts = 0
        max_attempts = batch_size * 3

        while len(batch) < batch_size and attempts < max_attempts:
            candidate = self._generate_random_candidate()
            candidate_hash = hashlib.md5(candidate.encode()).hexdigest()

            if candidate_hash not in self.tested_combinations:
                self.tested_combinations.add(candidate_hash)

                # 管理记忆大小
                if len(self.tested_combinations) > self.memory_size:
                    # 移除最旧的记录（转换为列表后取前n个）
                    items_list = list(self.tested_combinations)
                    self.tested_combinations = set(items_list[self.memory_size // 2:])

                if self._satisfies_clues(candidate):
                    batch.append(candidate)

            attempts += 1

        return batch

    def _generate_rotating_random_batch(self, batch_size):
        """生成轮换随机批次"""
        # 检查是否需要更换种子
        self._rotate_seed_if_needed()

        batch = []
        rng = random.Random(self.current_seed + str(self.generation_count))
        self.generation_count += 1

        attempts = 0
        max_attempts = batch_size * 3

        while len(batch) < batch_size and attempts < max_attempts:
            candidate = self._generate_candidate(rng)
            candidate_hash = hashlib.md5(candidate.encode()).hexdigest()

            if candidate_hash not in self.tested_combinations:
                self.tested_combinations.add(candidate_hash)

                if self._satisfies_clues(candidate):
                    batch.append(candidate)

            attempts += 1

        # 更新无结果计数器
        if not batch:
            self.attempts_since_last_found += attempts
        else:
            self.attempts_since_last_found = 0

        return batch

    def _index_to_candidate(self, index):
        """将索引转换为候选WIF"""
        candidate = list(self.template)
        temp_index = index

        for idx in self.variable_indices:
            candidates = self.position_candidates.get(str(idx + 1), "")
            if candidates:
                choice_index = temp_index % len(candidates)
                candidate[idx] = candidates[choice_index]
                temp_index = temp_index // len(candidates)

        return ''.join(candidate)

    def _generate_random_candidate(self):
        """生成随机候选"""
        candidate = list(self.template)
        for idx in self.variable_indices:
            candidates = self.position_candidates.get(str(idx + 1), "")
            if candidates:
                chosen_char = random.choice(candidates)
                candidate[idx] = chosen_char
        return ''.join(candidate)

    def _generate_candidate(self, rng):
        """使用指定RNG生成候选"""
        candidate = list(self.template)
        for idx in self.variable_indices:
            candidates = self.position_candidates.get(str(idx + 1), "")
            if candidates:
                chosen_char = rng.choice(candidates)
                candidate[idx] = chosen_char
        return ''.join(candidate)

    def _satisfies_clues(self, wif: str) -> bool:
        """检查WIF是否符合线索"""
        if len(wif) < 12:
            return True

        first_12 = wif[:12]

        # 字符集定义
        DIGITS = "123456789"
        UPPERCASE = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        LOWERCASE = "abcdefghijkmnopqrstuvwxyz"

        if self.clues.get('no_all_digits', False):
            if all(c in DIGITS for c in first_12):
                return False

        if self.clues.get('no_all_lowercase', False):
            if all(c in LOWERCASE for c in first_12):
                return False

        if self.clues.get('no_all_uppercase', False):
            if all(c in UPPERCASE for c in first_12):
                return False

        return True

    def is_search_complete(self):
        """检查搜索是否完成"""
        if self.search_mode == "sequential_partitioned":
            return self.current_index >= self.end_index
        return False

    def get_search_info(self):
        """获取搜索信息"""
        info = {
            'mode': self.search_mode,
            'strategy': self.search_strategy['description'],
            'rotation_count': self.rotation_count
        }

        if self.search_mode == "sequential_partitioned":
            info['progress'] = f"{self.current_index - self.start_index:,}/{self.end_index - self.start_index:,}"
            info['percentage'] = ((self.current_index - self.start_index) / (
                        self.end_index - self.start_index)) * 100 if self.end_index > self.start_index else 0
        elif self.search_mode == "partitioned_random_rotating":
            elapsed_hours = (time.time() - self.current_seed_start_time) / 3600
            info['current_seed_age'] = f"{elapsed_hours:.1f}小时"
            info['attempts_since_found'] = self.attempts_since_last_found

        return info


# ================== GPU验证器 ==================

class WIFValidatorGPU:
    """GPU加速的WIF验证器"""

    def __init__(self):
        self.device = DEVICE

    def verify_checksum_gpu_batch(self, wif_batch: List[str]) -> Tuple[List[bool], List[str]]:
        """批量验证WIF校验和"""
        valid_mask = []
        valid_wifs = []

        with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
            chunk_size = max(1, len(wif_batch) // (NUM_WORKERS * 4))
            chunks = [wif_batch[i:i + chunk_size] for i in range(0, len(wif_batch), chunk_size)]
            results = list(executor.map(self._verify_chunk, chunks))

            for chunk_valid_mask, chunk_valid_wifs in results:
                valid_mask.extend(chunk_valid_mask)
                valid_wifs.extend(chunk_valid_wifs)

        return valid_mask, valid_wifs

    def _verify_chunk(self, wif_chunk: List[str]) -> Tuple[List[bool], List[str]]:
        """处理一个数据块的验证"""
        valid_mask = []
        valid_wifs = []

        for wif in wif_chunk:
            try:
                decoded = base58.b58decode(wif)
                if len(decoded) not in [37, 38]:
                    valid_mask.append(False)
                    continue

                data = decoded[:-4]
                checksum = decoded[-4:]
                computed_checksum = double_sha256(data)[:4]

                if checksum == computed_checksum and data[0] == 0x80:
                    valid_mask.append(True)
                    valid_wifs.append(wif)
                else:
                    valid_mask.append(False)
            except:
                valid_mask.append(False)

        return valid_mask, valid_wifs


def double_sha256(data: bytes) -> bytes:
    """计算双SHA256哈希"""
    first_sha = hashlib.sha256(data).digest()
    return hashlib.sha256(first_sha).digest()


def gpu_verify_wif_batch(wif_batch: List[str]) -> Tuple[List[bool], List[str]]:
    """GPU批量验证WIF"""
    validator = WIFValidatorGPU()
    return validator.verify_checksum_gpu_batch(wif_batch)


# ================== 工具函数 ==================

def wif_to_privkey(wif: str) -> Tuple[bytes, bool]:
    """检查WIF是否合法，并返回私钥字节和压缩标志"""
    raw = base58.b58decode_check(wif)
    if raw[0] != 0x80:
        raise ValueError("不是主网WIF（version != 0x80）")

    payload = raw[1:]
    if len(payload) == 32:
        return payload, False
    elif len(payload) == 33 and payload[-1] == 0x01:
        return payload[:-1], True
    else:
        raise ValueError("WIF长度不符合32或33字节")


def save_found_wif(wif: str, priv_hex: str, compressed: bool, found_count: int):
    """保存找到的WIF到文件"""
    try:
        with open("found_wifs.txt", 'a', encoding='utf-8') as f:
            f.write(f"=== 找到第{found_count}个有效WIF ===\n")
            f.write(f"节点: {NODE_ID}\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"WIF: {wif}\n")
            f.write(f"私钥: {priv_hex}\n")
            f.write(f"压缩: {compressed}\n")
            f.write("=" * 50 + "\n\n")
    except Exception as e:
        print(f"{Colors.RED}警告: 保存WIF到文件失败: {e}{Colors.END}")


def save_progress(tested_count: int, found_count: int):
    """保存本地进度"""
    progress_data = {
        "tested_count": tested_count,
        "found_count": found_count,
        "node_id": NODE_ID,
        "timestamp": time.time()
    }
    try:
        with open("miner_progress.json", 'w') as f:
            json.dump(progress_data, f, indent=2)
    except:
        pass


def load_progress():
    """加载本地进度"""
    try:
        with open("miner_progress.json", 'r') as f:
            return json.load(f)
    except:
        return None


# ================== 进度显示类 ==================

class MinerProgressDisplay:
    """矿工进度显示"""

    def __init__(self, distributed_mgr: DistributedManager, search_manager: AdaptiveSearchManager):
        self.distributed_mgr = distributed_mgr
        self.search_manager = search_manager
        self.start_time = time.time()
        self.last_update = self.start_time
        self.last_display_update = self.start_time
        self.tested_count = 0
        self.found_count = 0
        self.current_speed = 0
        self.speeds = []
        self.display_lines = 10
        self.testing_wifs = []
        self.animation_chars = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        self.anim_index = 0

    def update(self, tested_increment: int, found_increment: int = 0, current_batch: List[str] = None):
        """更新进度显示"""
        self.tested_count += tested_increment
        self.found_count += found_increment

        current_time = time.time()
        time_diff = current_time - self.last_update

        if time_diff > 0:
            batch_speed = tested_increment / time_diff
            self.speeds.append(batch_speed)
            if len(self.speeds) > 5:
                self.speeds.pop(0)
            self.current_speed = sum(self.speeds) / len(self.speeds)
            self.last_update = current_time

        # 保存测试样本
        if current_batch and len(current_batch) > 0:
            sample_size = min(3, len(current_batch))
            self.testing_wifs = random.sample(current_batch, sample_size)

        # 每秒更新一次显示
        if current_time - self.last_display_update >= 1.0:
            self._display_progress()
            self.last_display_update = current_time

    def _display_progress(self):
        """显示进度信息"""
        # 清空之前的显示区域
        for i in range(self.display_lines):
            sys.stdout.write('\033[K')
            if i < self.display_lines - 1:
                sys.stdout.write('\033[1A')

        elapsed_time = time.time() - self.start_time
        search_info = self.search_manager.get_search_info()

        # 动画字符
        self.anim_index = (self.anim_index + 1) % len(self.animation_chars)
        anim_char = self.animation_chars[self.anim_index]

        # 动态进度条
        bar_length = 40
        if search_info['mode'] == 'sequential_partitioned' and 'percentage' in search_info:
            # 顺序搜索显示真实进度
            progress_ratio = search_info['percentage'] / 100
            bar_fill = "█"
        else:
            # 随机搜索显示动态进度
            progress_ratio = (elapsed_time % 60) / 60
            bar_fill = "▶"

        filled_length = int(bar_length * progress_ratio)
        bar = bar_fill * filled_length + "░" * (bar_length - filled_length)

        # 格式化输出
        print(f"{Colors.CYAN}{Colors.BOLD}🎯 自适应搜索中... {anim_char}{Colors.END}")
        print(f"{Colors.WHITE}╔══════════════════════════════════════════════════════════════════════════╗{Colors.END}")

        # 节点信息
        node_line = f"║ {Colors.YELLOW}节点:{Colors.END} {NODE_ID}"
        if self.distributed_mgr.connected:
            node_line += f" {Colors.GREEN}(已连接){Colors.END}"
        else:
            node_line += f" {Colors.RED}(独立){Colors.END}"
        node_line += f" {Colors.CYAN}策略:{Colors.END} {search_info['mode']}"
        node_line += " " * (30) + "║"
        print(node_line)

        # 统计信息
        stats_line = f"║ {Colors.YELLOW}尝试次数:{Colors.END} {self.tested_count:,}"
        stats_line += f" {Colors.GREEN}找到数量:{Colors.END} {Colors.BOLD}{self.found_count}{Colors.END}"

        if 'progress' in search_info:
            stats_line += f" {Colors.MAGENTA}进度:{Colors.END} {search_info['progress']}"
        stats_line += " " * (15) + "║"
        print(stats_line)

        # 速度信息
        speed_line = f"║ {Colors.BLUE}搜索速度:{Colors.END} {self.current_speed:,.0f} WIF/秒"
        speed_line += f" {Colors.MAGENTA}运行时间:{Colors.END} {self._format_time(elapsed_time)}"

        if 'current_seed_age' in search_info:
            speed_line += f" {Colors.CYAN}种子年龄:{Colors.END} {search_info['current_seed_age']}"
        speed_line += " " * (5) + "║"
        print(speed_line)

        # 搜索策略信息
        strategy_line = f"║ {Colors.CYAN}搜索策略:{Colors.END} {search_info['strategy']}"
        if search_info['rotation_count'] > 0:
            strategy_line += f" {Colors.YELLOW}轮换:{Colors.END} {search_info['rotation_count']}次"
        strategy_line += " " * (20) + "║"
        print(strategy_line)

        # 动态进度条
        progress_text = "完成进度" if search_info['mode'] == 'sequential_partitioned' else "搜索状态"
        if 'percentage' in search_info:
            progress_line = f"║ {Colors.CYAN}{progress_text}:{Colors.END} [{Colors.GREEN}{bar}{Colors.END}] {search_info['percentage']:.1f}%"
        else:
            progress_line = f"║ {Colors.CYAN}{progress_text}:{Colors.END} [{Colors.GREEN}{bar}{Colors.END}]"
        progress_line += " " * (20) + "║"
        print(progress_line)

        # 测试样本显示
        if self.testing_wifs:
            sample_line = f"║ {Colors.CYAN}测试样本:{Colors.END} "
            sample_display = []
            for wif in self.testing_wifs:
                short_wif = wif[:8] + "..." + wif[-6:]
                sample_display.append(short_wif)

            sample_line += ", ".join(sample_display)
            if len(sample_line) > 78:
                sample_line = sample_line[:75] + "..."
            sample_line += " " * (78 - len(sample_line)) + "║"
            print(sample_line)

        print(f"{Colors.WHITE}╚══════════════════════════════════════════════════════════════════════════╝{Colors.END}")
        print(f"{Colors.YELLOW}按 Ctrl+C 可安全停止 | 策略: {search_info['strategy']}{Colors.END}")

        sys.stdout.flush()

    def _format_time(self, seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}分{secs}秒"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}时{mins}分"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f"{days}天{hours}时"

    def complete(self, reason=""):
        """完成显示"""
        total_time = time.time() - self.start_time
        # 清空显示区域
        for i in range(self.display_lines):
            sys.stdout.write('\033[K')
            if i < self.display_lines - 1:
                sys.stdout.write('\033[1A')

        print(f"\n{Colors.GREEN}{Colors.BOLD}🎊 搜索完成!{Colors.END}")
        if reason:
            print(f"{Colors.YELLOW}原因: {reason}{Colors.END}")
        print(f"{Colors.CYAN}{'═' * 60}{Colors.END}")
        print(f"{Colors.WHITE}总用时:{Colors.END} {Colors.BOLD}{self._format_time(total_time)}{Colors.END}")
        print(f"{Colors.WHITE}总尝试:{Colors.END} {Colors.BOLD}{self.tested_count:,}{Colors.END} 次")
        print(
            f"{Colors.WHITE}平均速度:{Colors.END} {Colors.BOLD}{self.tested_count / total_time:,.0f} WIF/秒{Colors.END}")
        print(f"{Colors.WHITE}找到WIF:{Colors.END} {Colors.BOLD}{Colors.GREEN}{self.found_count}{Colors.END} 个")

        if self.found_count > 0:
            efficiency = self.tested_count / self.found_count
            print(f"{Colors.WHITE}搜索效率:{Colors.END} {Colors.BOLD}{efficiency:,.0f} 次尝试/有效WIF{Colors.END}")

        print(f"{Colors.CYAN}{'═' * 60}{Colors.END}")


# ================== 主逻辑 ==================

def display_miner_info(distributed_mgr: DistributedManager):
    """显示矿工信息"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}           WIF搜索矿工 - 自适应搜索模式{Colors.END}")
    print(f"{Colors.CYAN}{'=' * 70}{Colors.END}")

    print(f"{Colors.YELLOW}📋 节点信息:{Colors.END}")
    print(f"  {Colors.WHITE}• 节点ID:{Colors.END} {Colors.BOLD}{NODE_ID}{Colors.END}")
    print(f"  {Colors.WHITE}• 主节点:{Colors.END} {Colors.BOLD}{MASTER_NODE}:{MASTER_PORT}{Colors.END}")
    print(f"  {Colors.WHITE}• 设备:{Colors.END} {Colors.BOLD}{DEVICE}{Colors.END}")
    print(f"  {Colors.WHITE}• 工作进程:{Colors.END} {Colors.BOLD}{NUM_WORKERS}{Colors.END}")


def main():
    # 初始化分布式管理器
    distributed_mgr = DistributedManager()

    # 显示矿工信息
    display_miner_info(distributed_mgr)

    # 尝试连接主节点获取配置
    config_loaded = distributed_mgr.load_config_from_master()

    if not config_loaded:
        print(f"{Colors.YELLOW}⚠️  无法连接到主节点，使用默认配置独立运行{Colors.END}")
        # 使用默认配置
        default_config = {
            'template_wif': "1111111111115bCRZhiS5sEGMpmcRZdpAhmWLRfMmutGmPHtjVob",
            'position_candidates': {
                "1": "KL",
                "2": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "3": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "4": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "5": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "6": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "7": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "8": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "9": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "10": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "11": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
                "12": "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            },
            'search_strategy': {
                'mode': 'partitioned_random_rotating',
                'description': '大空间轮换随机搜索',
                'rotation_interval_hours': 24,
                'max_attempts_no_result': 100000000
            },
            'base_seed': hashlib.sha256(NODE_ID.encode()).hexdigest(),
            'batch_size': BATCH_SIZE,
            'total_nodes': 1,
            'node_index': 0,
            'clues': {
                'no_all_digits': True,
                'no_all_lowercase': True,
                'no_all_uppercase': True
            },
            'search_space_info': {
                'total_combinations': 10 ** 15,  # 假设大空间
                'space_type': 'large',
                'description': '大空间轮换随机搜索+时间限制'
            }
        }
        distributed_mgr.config = default_config

    # 恢复本地进度
    progress = load_progress()
    if progress and progress.get('node_id') == NODE_ID:
        tested = progress.get('tested_count', 0)
        found_count = progress.get('found_count', 0)
        print(f"{Colors.GREEN}📂 恢复本地进度: {tested:,} 尝试, {found_count} 找到{Colors.END}")
    else:
        tested = 0
        found_count = 0

    # 初始化自适应搜索管理器
    search_manager = AdaptiveSearchManager(
        distributed_mgr.config['template_wif'],
        distributed_mgr.config['position_candidates'],
        distributed_mgr.config['base_seed'],
        distributed_mgr.config['clues'],
        distributed_mgr.config['total_nodes'],
        distributed_mgr.config['node_index'],
        distributed_mgr.config['search_strategy'],
        distributed_mgr.config['search_space_info']
    )

    # 初始化进度显示器
    progress_display = MinerProgressDisplay(distributed_mgr, search_manager)
    progress_display.tested_count = tested
    progress_display.found_count = found_count

    # 信号处理
    def signal_handler(sig, frame):
        print(f"\n\n{Colors.RED}🛑 停止搜索! 正在保存进度...{Colors.END}")
        save_progress(progress_display.tested_count, progress_display.found_count)
        progress_display.complete("用户中断")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 主处理循环
    start_time = time.time()
    last_save_time = start_time
    last_report_time = start_time
    batch_count = 0

    print(f"\n{Colors.CYAN}🚀 开始自适应搜索...{Colors.END}")
    print(f"{Colors.YELLOW}策略: {distributed_mgr.config['search_strategy']['description']}{Colors.END}")

    try:
        while True:
            # 检查搜索是否完成（对于顺序搜索）
            if search_manager.is_search_complete():
                print(f"{Colors.GREEN}✅ 搜索任务完成!{Colors.END}")
                break

            # 生成候选批次
            batch = search_manager.generate_batch(distributed_mgr.config['batch_size'])

            # 如果批次为空且是顺序搜索，说明完成
            if not batch and search_manager.search_mode == "sequential_partitioned":
                print(f"{Colors.GREEN}✅ 顺序搜索完成!{Colors.END}")
                break

            batch_count += 1

            # 验证批次
            valid_mask, valid_wifs = gpu_verify_wif_batch(batch)
            tested_increment = len(batch)

            # 处理有效WIF
            for wif in valid_wifs:
                try:
                    priv_bytes, compressed = wif_to_privkey(wif)
                    found_count += 1

                    # 显示找到的WIF
                    print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 发现第 {found_count} 个有效WIF!{Colors.END}")
                    print(f"{Colors.CYAN}{'─' * 60}{Colors.END}")
                    print(f"{Colors.WHITE}🔑 WIF:{Colors.END} {Colors.BOLD}{Colors.GREEN}{wif}{Colors.END}")
                    print(f"{Colors.WHITE}🗝️  私钥:{Colors.END} {Colors.YELLOW}{priv_bytes.hex()}{Colors.END}")
                    print(
                        f"{Colors.WHITE}📦 压缩格式:{Colors.END} {Colors.BLUE}{'是' if compressed else '否'}{Colors.END}")
                    print(f"{Colors.WHITE}⏰ 发现时间:{Colors.END} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(
                        f"{Colors.WHITE}🎲 本机尝试次数:{Colors.END} {progress_display.tested_count + tested_increment:,}")
                    print(f"{Colors.WHITE}🏠 发现节点:{Colors.END} {NODE_ID}")
                    print(f"{Colors.WHITE}🔍 搜索策略:{Colors.END} {search_manager.search_mode}")
                    print(f"{Colors.CYAN}{'─' * 60}{Colors.END}")

                    # 保存到本地文件
                    save_found_wif(wif, priv_bytes.hex(), compressed, found_count)

                    # 报告到主节点
                    if distributed_mgr.connected:
                        wif_data = {
                            'wif': wif,
                            'private_key': priv_bytes.hex(),
                            'compressed': compressed,
                            'found_count': found_count
                        }
                        distributed_mgr.report_found_wif(wif_data)

                except Exception as e:
                    print(f"{Colors.RED}警告: 处理有效WIF时出错: {e}{Colors.END}")
                    continue

            # 更新进度显示
            progress_display.update(tested_increment, len(valid_wifs), batch)

            # 向主节点报告进度（每10秒一次）
            current_time = time.time()
            if distributed_mgr.connected and current_time - last_report_time >= 10:
                distributed_mgr.report_progress(progress_display.tested_count, progress_display.found_count)
                last_report_time = current_time

            # 保存本地进度（每30秒一次）
            if current_time - last_save_time >= 30:
                save_progress(progress_display.tested_count, progress_display.found_count)
                last_save_time = current_time

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}用户中断搜索{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}❌ 发生错误: {e}{Colors.END}")
        import traceback
        traceback.print_exc()

    # 完成处理
    save_progress(progress_display.tested_count, progress_display.found_count)

    if search_manager.is_search_complete():
        progress_display.complete("搜索任务完成")
    else:
        progress_display.complete()

    if found_count == 0:
        print(f"\n{Colors.YELLOW}在搜索中尚未找到合法WIF{Colors.END}")
    else:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎊 搜索完成！本机共找到{found_count}条合法WIF{Colors.END}")


if __name__ == "__main__":
    if sys.platform == "win32":
        mp.freeze_support()
    main()