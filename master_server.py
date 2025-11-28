from socketserver import ThreadingMixIn
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from datetime import datetime
import hashlib
import os
import sys
import socket

# 分布式文件
DISTRIBUTED_PROGRESS_FILE = "distributed_progress.json"
FOUND_WIFS_FILE = "found_wifs.txt"
MASTER_CONFIG_FILE = "master_config.json"


# 添加线程化HTTP服务器类
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """线程化的HTTP服务器，支持并发处理"""
    daemon_threads = True
    timeout = 30  # 设置连接超时

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 设置socket选项，避免地址占用
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


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
    END = '\033[0m'


class MasterRequestHandler(BaseHTTPRequestHandler):
    """主节点HTTP请求处理器"""

    # 设置更长的超时时间
    timeout = 30

    def __init__(self, *args, **kwargs):
        self.config = self.load_config()
        super().__init__(*args, **kwargs)

    def load_config(self):
        """加载主配置"""
        default_config = {
            "template_wif": "1111111111115bCRZhiS5sEGMpmcRZdpAhmWLRfMmutGmPHtjVob",
            "position_candidates": {
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
            "search_mode": "adaptive",
            "total_nodes": 50,
            "batch_size": 100000,
            "node_assignments": {},
            "clues": {
                "no_all_digits": True,
                "no_all_lowercase": True,
                "no_all_uppercase": True
            },
            "adaptive_config": {
                "small_space_threshold": 1000000,
                "medium_space_threshold": 100000000,
                "rotation_interval_hours": 24,
                "max_attempts_no_result": 100000000
            }
        }

        try:
            with open(MASTER_CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                # 合并配置
                default_config.update(user_config)
        except:
            print(f"{Colors.YELLOW}⚠️  使用默认配置，创建配置文件...{Colors.END}")

        # 确保数值类型正确
        self._ensure_numeric_types(default_config)

        # 保存配置
        self.save_config(default_config)
        return default_config

    def _ensure_numeric_types(self, config):
        """确保配置中的数值类型正确"""
        # 转换整数类型
        if 'total_nodes' in config:
            config['total_nodes'] = int(config['total_nodes'])
        if 'batch_size' in config:
            config['batch_size'] = int(config['batch_size'])

        # 转换自适应配置中的数值
        if 'adaptive_config' in config:
            adaptive_config = config['adaptive_config']
            numeric_keys = ['small_space_threshold', 'medium_space_threshold',
                            'rotation_interval_hours', 'max_attempts_no_result']
            for key in numeric_keys:
                if key in adaptive_config:
                    adaptive_config[key] = int(adaptive_config[key])

    def save_config(self, config=None):
        """保存配置"""
        if config is None:
            config = self.config
        try:
            with open(MASTER_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"{Colors.RED}❌ 保存配置失败: {e}{Colors.END}")

    def log_message(self, format, *args):
        """自定义日志格式，减少输出噪音"""
        # 只记录重要请求，过滤掉频繁的进度报告
        if self.path not in ['/progress', '/config']:
            timestamp = datetime.now().strftime('%H:%M:%S')
            client_ip = self.client_address[0]
            print(f"{Colors.CYAN}[{timestamp}]{Colors.END} {Colors.YELLOW}{client_ip}{Colors.END} - {format % args}")
        elif self.path == '/progress':
            # 进度报告只显示简略信息
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"{Colors.CYAN}[{timestamp}]{Colors.END} {Colors.GREEN}📊 进度更新{Colors.END}")

    def handle_one_request(self):
        """处理单个请求，增加异常处理"""
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, socket.timeout) as e:
            print(f"{Colors.YELLOW}⚠️  连接异常: {e}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}❌ 请求处理异常: {e}{Colors.END}")

    def do_GET(self):
        """处理GET请求"""
        try:
            if self.path == '/progress':
                progress = self.load_progress()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'total_tested': progress['total_tested'],
                    'total_found': progress['total_found'],
                    'active_nodes': len(progress['nodes']),
                    'nodes': progress['nodes'],
                    'timestamp': time.time()
                }).encode())

            elif self.path == '/status':
                progress = self.load_progress()
                found_wifs = self.load_found_wifs()
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Connection', 'close')
                self.end_headers()
                html = self._generate_status_page(progress, found_wifs)
                self.wfile.write(html.encode('utf-8'))

            elif self.path == '/config':
                node_config = self.generate_node_config()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(json.dumps(node_config).encode())
                print(f"{Colors.GREEN}✅ 向 {self.client_address[0]} 提供配置{Colors.END}")

            elif self.path == '/admin':
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Connection', 'close')
                self.end_headers()
                html = self._generate_admin_page()
                self.wfile.write(html.encode('utf-8'))

            elif self.path == '/found':
                found_wifs = self.load_found_wifs()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'found_count': len(found_wifs),
                    'found_wifs': found_wifs,
                    'timestamp': time.time()
                }).encode())

            elif self.path == '/node_stats':
                progress = self.load_progress()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'nodes': progress['nodes'],
                    'total_stats': self._calculate_total_stats(progress['nodes']),
                    'timestamp': time.time()
                }).encode())

            else:
                self.send_response(404)
                self.send_header('Connection', 'close')
                self.end_headers()
        except Exception as e:
            print(f"{Colors.RED}❌ GET请求处理错误: {e}{Colors.END}")
            try:
                self.send_error(500, str(e))
            except:
                pass

    def do_POST(self):
        """处理POST请求"""
        try:
            if self.path == '/progress':
                self.handle_progress_report()
            elif self.path == '/found_wif':
                self.handle_found_wif()
            elif self.path == '/update_config':
                self.handle_config_update()
            elif self.path == '/register':
                self.handle_node_register()
            else:
                self.send_response(404)
                self.send_header('Connection', 'close')
                self.end_headers()
        except Exception as e:
            print(f"{Colors.RED}❌ POST请求处理错误: {e}{Colors.END}")
            try:
                self.send_error(500, str(e))
            except:
                pass

    def handle_progress_report(self):
        """处理进度报告，增加连接稳定性"""
        try:
            client_ip = self.client_address[0]
            print(f"{Colors.CYAN}📥 收到进度报告来自 {client_ip}{Colors.END}")

            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())

            print(f"{Colors.GREEN}📥 收到进度报告:{Colors.END}")
            print(f"  节点ID: {data.get('node_id')}")
            print(f"  尝试次数: {data.get('tested_count', 0):,}")
            print(f"  找到数量: {data.get('found_count', 0)}")

            progress = self.load_progress()
            node_id = data['node_id']
            tested_count = data['tested_count']
            found_count = data['found_count']
            partition_seed = data.get('partition_seed', 'unknown')
            current_time = time.time()

            if node_id not in progress['nodes']:
                progress['nodes'][node_id] = {
                    'register_time': current_time,
                    'first_update': current_time,
                    'last_reported_count': 0,
                    'total_attempts': 0,
                    'session_attempts': 0,
                    'tested_count': 0,
                    'found_count': 0
                }

            node_data = progress['nodes'][node_id]
            previous_count = node_data.get('last_reported_count', 0)
            session_increment = tested_count - previous_count

            node_data['session_attempts'] = node_data.get('session_attempts', 0) + session_increment
            node_data['total_attempts'] = node_data.get('total_attempts', 0) + session_increment
            node_data['last_reported_count'] = tested_count

            node_data['tested_count'] = tested_count
            node_data['found_count'] = found_count
            node_data['last_update'] = current_time
            node_data['ip_address'] = self.client_address[0]
            node_data['partition_seed'] = partition_seed

            if 'first_update' not in node_data:
                node_data['first_update'] = current_time
            node_data['online_duration'] = current_time - node_data['first_update']

            progress['total_tested'] = sum(node['tested_count'] for node in progress['nodes'].values())
            progress['total_found'] = sum(node['found_count'] for node in progress['nodes'].values())
            progress['last_updated'] = current_time

            self.save_progress(progress)

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Connection', 'close')
            self.end_headers()

            print(f"{Colors.GREEN}✅ 进度更新完成，当前节点数: {len(progress['nodes'])}{Colors.END}")
            print(
                f"  节点 {node_id}: 增量 {session_increment:,}, 总尝试 {node_data['total_attempts']:,}, 在线 {node_data['online_duration']:.0f}秒")

        except socket.timeout:
            print(f"{Colors.YELLOW}⏰ 请求超时: {self.client_address[0]}{Colors.END}")
            try:
                self.send_error(408, "Request Timeout")
            except:
                pass
        except ConnectionResetError:
            print(f"{Colors.YELLOW}🔌 连接重置: {self.client_address[0]}{Colors.END}")
        except Exception as e:
            print(f"{Colors.RED}❌ 处理进度报告出错: {e}{Colors.END}")
            try:
                self.send_error(500, str(e))
            except:
                pass

    def handle_found_wif(self):
        """处理找到的WIF"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())

            wif = data['wif']
            private_key = data['private_key']
            compressed = data['compressed']
            node_id = data['node_id']
            found_count = data['found_count']

            self.save_found_wif(wif, private_key, compressed, node_id, found_count)

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Connection', 'close')
            self.end_headers()

            print(f"\n{Colors.GREEN}{Colors.BOLD}{'🎉' * 10} 发现有效WIF！{'🎉' * 10}{Colors.END}")
            print(f"{Colors.GREEN}🏠 发现节点: {node_id}{Colors.END}")
            print(f"{Colors.GREEN}🔑 WIF: {wif}{Colors.END}")
            print(f"{Colors.GREEN}🗝️  私钥: {private_key}{Colors.END}")
            print(f"{Colors.GREEN}📦 压缩: {'是' if compressed else '否'}{Colors.END}")
            print(f"{Colors.GREEN}🎯 序号: 第{found_count}个{Colors.END}")
            print(f"{Colors.GREEN}{Colors.BOLD}{'🎉' * 10}{'🎉' * 10}{Colors.END}\n")

        except Exception as e:
            try:
                self.send_response(500)
                self.send_header('Connection', 'close')
                self.end_headers()
            except:
                pass
            print(f"{Colors.RED}❌ 保存WIF记录失败: {e}{Colors.END}")

    def handle_config_update(self):
        """处理配置更新"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())

            update_fields = []
            for key, value in data.items():
                if key in ['template_wif', 'search_mode']:
                    self.config[key] = value
                    update_fields.append(key)
                elif key in ['total_nodes', 'batch_size']:
                    try:
                        self.config[key] = int(value)
                        update_fields.append(key)
                    except ValueError:
                        print(f"{Colors.YELLOW}⚠️  忽略无效数值: {key}={value}{Colors.END}")
                elif key == 'position_count':
                    pass
                elif key in ['no_all_digits', 'no_all_lowercase', 'no_all_uppercase']:
                    self.config['clues'][key] = (value == 'on')
                    update_fields.append(f"clues.{key}")
                elif key.startswith('adaptive_'):
                    config_key = key.replace('adaptive_', '')
                    if config_key in self.config['adaptive_config']:
                        try:
                            self.config['adaptive_config'][config_key] = int(value)
                            update_fields.append(f"adaptive.{config_key}")
                        except ValueError:
                            print(f"{Colors.YELLOW}⚠️  忽略无效自适应配置: {config_key}={value}{Colors.END}")

            self._ensure_numeric_types(self.config)
            self.save_config()

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'success', 'updated': update_fields}).encode())

            print(f"{Colors.GREEN}✅ 配置已更新: {update_fields}{Colors.END}")

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode())
            print(f"{Colors.RED}❌ 更新配置失败: {e}{Colors.END}")

    def handle_node_register(self):
        """处理节点注册"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())

            node_id = data.get('node_id', 'Unknown')
            hostname = data.get('hostname', 'Unknown')

            print(f"{Colors.GREEN}🎯 新节点注册: {node_id} ({hostname}) - {self.client_address[0]}{Colors.END}")

            progress = self.load_progress()
            if node_id not in progress['nodes']:
                current_time = time.time()
                progress['nodes'][node_id] = {
                    'register_time': current_time,
                    'first_update': current_time,
                    'ip_address': self.client_address[0],
                    'hostname': hostname,
                    'tested_count': 0,
                    'found_count': 0,
                    'total_attempts': 0,
                    'session_attempts': 0,
                    'online_duration': 0
                }
                self.save_progress(progress)

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Connection', 'close')
            self.end_headers()

        except Exception as e:
            print(f"{Colors.RED}❌ 节点注册失败: {e}{Colors.END}")
            self.send_response(500)
            self.send_header('Connection', 'close')
            self.end_headers()

    def generate_node_config(self):
        """为节点生成唯一配置"""
        client_ip = self.client_address[0]
        node_id = f"node_{hashlib.md5(client_ip.encode()).hexdigest()[:8]}"

        partition_seed = self.generate_partition_seed(node_id)

        if node_id not in self.config['node_assignments']:
            self.config['node_assignments'][node_id] = {
                'ip': client_ip,
                'partition_seed': partition_seed,
                'register_time': time.time(),
                'total_assigned': len(self.config['node_assignments']) + 1
            }
            self.save_config()

        search_space_info = self._calculate_search_space_info()

        return {
            'node_id': node_id,
            'template_wif': self.config['template_wif'],
            'position_candidates': self.config['position_candidates'],
            'search_strategy': self._get_adaptive_strategy(search_space_info['total_combinations']),
            'base_seed': partition_seed,
            'batch_size': self.config['batch_size'],
            'total_nodes': self.config['total_nodes'],
            'node_index': self.config['node_assignments'][node_id]['total_assigned'] - 1,
            'clues': self.config['clues'],
            'search_space_info': search_space_info
        }

    def generate_partition_seed(self, node_id):
        """生成分区种子"""
        seed_hash = hashlib.sha256(f"{node_id}_{time.time()}".encode()).hexdigest()
        return seed_hash

    def _calculate_search_space_info(self):
        """计算搜索空间信息"""
        total_combinations = 1
        variable_positions = []

        for pos_str, candidates in self.config['position_candidates'].items():
            try:
                pos_int = int(pos_str)
                if 1 <= pos_int <= len(self.config['template_wif']):
                    total_combinations *= len(candidates)
                    variable_positions.append(pos_int)
            except ValueError:
                continue

        if total_combinations <= self.config['adaptive_config']['small_space_threshold']:
            space_type = "small"
        elif total_combinations <= self.config['adaptive_config']['medium_space_threshold']:
            space_type = "medium"
        else:
            space_type = "large"

        return {
            'total_combinations': total_combinations,
            'variable_positions': variable_positions,
            'space_type': space_type,
            'description': self._get_space_description(space_type, total_combinations)
        }

    def _get_space_description(self, space_type, total_combinations):
        """获取搜索空间描述"""
        descriptions = {
            "small": f"小空间 ({total_combinations:,} 组合) - 顺序搜索确保完全覆盖",
            "medium": f"中等空间 ({total_combinations:,} 组合) - 记忆随机搜索避免重复",
            "large": f"大空间 ({total_combinations:,} 组合) - 轮换随机搜索+时间限制"
        }
        return descriptions.get(space_type, "未知空间")

    def _get_adaptive_strategy(self, total_combinations):
        """获取自适应策略配置"""
        if total_combinations <= self.config['adaptive_config']['small_space_threshold']:
            return {
                'mode': 'sequential_partitioned',
                'description': '小空间顺序分区搜索',
                'max_attempts': total_combinations
            }
        elif total_combinations <= self.config['adaptive_config']['medium_space_threshold']:
            return {
                'mode': 'random_with_memory',
                'description': '中等空间记忆随机搜索',
                'memory_size': min(1000000, total_combinations // 10)
            }
        else:
            return {
                'mode': 'partitioned_random_rotating',
                'description': '大空间轮换随机搜索',
                'rotation_interval_hours': self.config['adaptive_config']['rotation_interval_hours'],
                'max_attempts_no_result': self.config['adaptive_config']['max_attempts_no_result']
            }

    def _calculate_total_stats(self, nodes):
        """计算总体统计信息"""
        total_attempts = sum(node.get('total_attempts', 0) for node in nodes.values())
        total_online_time = sum(node.get('online_duration', 0) for node in nodes.values())
        avg_speed = total_attempts / total_online_time if total_online_time > 0 else 0

        return {
            'total_attempts': total_attempts,
            'total_online_time': total_online_time,
            'avg_speed_per_second': avg_speed,
            'node_count': len(nodes)
        }

    # 管理员面板
    def _generate_admin_page(self):
        """生成管理页面"""
        node_rows = ""
        progress = self.load_progress()

        for node_id, data in self.config['node_assignments'].items():
            node_info = progress['nodes'].get(node_id, {})
            online_duration = node_info.get('online_duration', 0)
            total_attempts = node_info.get('total_attempts', 0)

            node_rows += f"""
                   <tr>
                       <td>{node_id}</td>
                       <td>{data['ip']}</td>
                       <td style="font-family: monospace; font-size: 12px;">{data['partition_seed'][:16]}...</td>
                       <td>{datetime.fromtimestamp(data['register_time']).strftime('%m-%d %H:%M')}</td>
                       <td>#{data['total_assigned']}</td>
                       <td>{self._format_duration(online_duration)}</td>
                       <td>{total_attempts:,}</td>
                   </tr>
                   """

        if not node_rows:
            node_rows = '<tr><td colspan="7" style="text-align: center; color: #999;">暂无节点注册</td></tr>'

        search_space_info = self._calculate_search_space_info()

        return f"""
               <!DOCTYPE html>
               <html>
               <head>
                   <title>WIF集群管理</title>
                   <meta charset="utf-8">
                   <style>
                       body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                       .container {{ max-width: 1200px; margin: 0 auto; }}
                       .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
                       .config-section {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                       .form-group {{ margin-bottom: 15px; }}
                       label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
                       input[type="text"], textarea, select {{ 
                           width: 100%; 
                           padding: 8px; 
                           border: 1px solid #ddd; 
                           border-radius: 4px; 
                           box-sizing: border-box;
                       }}
                       textarea {{ height: 100px; resize: vertical; }}
                       button {{ 
                           background: #3498db; 
                           color: white; 
                           padding: 10px 20px; 
                           border: none; 
                           border-radius: 5px; 
                           cursor: pointer; 
                           font-size: 16px;
                       }}
                       button:hover {{ background: #2980b9; }}
                       .node-table {{ width: 100%; border-collapse: collapse; }}
                       .node-table th, .node-table td {{ 
                           padding: 10px; 
                           text-align: left; 
                           border-bottom: 1px solid #ddd; 
                       }}
                       .node-table th {{ background: #f8f9fa; }}
                       .success-message {{ 
                           background: #d4edda; 
                           color: #155724; 
                           padding: 10px; 
                           border-radius: 4px; 
                           margin: 10px 0;
                       }}
                       .info-card {{ background: #e8f4fd; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                   </style>
                   <script>
                       function updateConfig() {{
                           const form = document.getElementById('configForm');
                           const formData = new FormData(form);
                           const data = Object.fromEntries(formData);

                           fetch('/update_config', {{
                               method: 'POST',
                               headers: {{
                                   'Content-Type': 'application/json',
                               }},
                               body: JSON.stringify(data)
                           }})
                           .then(response => response.json())
                           .then(result => {{
                               const messageDiv = document.getElementById('message');
                               messageDiv.innerHTML = '<div class="success-message">✅ 配置更新成功！所有节点将在下次请求时获取新配置。</div>';
                               setTimeout(() => messageDiv.innerHTML = '', 3000);
                           }})
                           .catch(error => {{
                               console.error('Error:', error);
                           }});
                       }}

                       function updateTemplate() {{
                           const template = document.getElementById('template_wif').value;
                           const questionCount = (template.match(/\?/g) || []).length;
                           document.getElementById('position_count').value = questionCount;
                       }}
                   </script>
               </head>
               <body>
                   <div class="container">
                       <div class="header">
                           <h1>🎯 WIF搜索集群管理系统</h1>
                           <p>自适应搜索策略 - 主节点控制面板</p>
                       </div>

                       <div id="message"></div>

                       <div class="config-section">
                           <h2>📊 搜索空间分析</h2>
                           <div class="info-card">
                               <p><strong>空间类型:</strong> {search_space_info['space_type'].upper()}</p>
                               <p><strong>总组合数:</strong> {search_space_info['total_combinations']:,}</p>
                               <p><strong>可变位置:</strong> {search_space_info['variable_positions']}</p>
                               <p><strong>推荐策略:</strong> {search_space_info['description']}</p>
                           </div>
                       </div>

                       <div class="config-section">
                           <h2>📝 搜索模板配置</h2>
                           <form id="configForm">
                               <div class="form-group">
                                   <label for="template_wif">模板WIF:</label>
                                   <input type="text" id="template_wif" name="template_wif" 
                                          value="{self.config['template_wif']}" 
                                          oninput="updateTemplate()"
                                          placeholder="例如: L3s8oBdcmjZSbQek4s1vLFUgvg3vwL6Vn1VhZEoffDF2e4??????">
                                   <small>使用 ? 表示不确定的位置</small>
                               </div>

                               <div class="form-group">
                                   <label for="position_count">不确定位置数量:</label>
                                   <input type="number" id="position_count" name="position_count" 
                                          value="{self.config['template_wif'].count('?')}" readonly>
                               </div>

                               <div class="form-group">
                                   <label for="search_mode">搜索模式:</label>
                                   <select id="search_mode" name="search_mode">
                                       <option value="adaptive" {'selected' if self.config['search_mode'] == 'adaptive' else ''}>自适应策略</option>
                                       <option value="sequential" {'selected' if self.config['search_mode'] == 'sequential' else ''}>顺序搜索</option>
                                       <option value="random" {'selected' if self.config['search_mode'] == 'random' else ''}>随机搜索</option>
                                   </select>
                               </div>

                               <div class="form-group">
                                   <label for="total_nodes">目标节点数量:</label>
                                   <input type="number" id="total_nodes" name="total_nodes" 
                                          value="{self.config['total_nodes']}">
                               </div>

                               <div class="form-group">
                                   <label for="batch_size">批次大小:</label>
                                   <input type="number" id="batch_size" name="batch_size" 
                                          value="{self.config['batch_size']}">
                               </div>

                               <div class="form-group">
                                   <label>线索设置:</label><br>
                                   <input type="checkbox" id="no_all_digits" name="no_all_digits" {'checked' if self.config['clues']['no_all_digits'] else ''}>
                                   <label for="no_all_digits" style="display: inline;">前12位不能全是数字</label><br>

                                   <input type="checkbox" id="no_all_lowercase" name="no_all_lowercase" {'checked' if self.config['clues']['no_all_lowercase'] else ''}>
                                   <label for="no_all_lowercase" style="display: inline;">前12位不能全是小写</label><br>

                                   <input type="checkbox" id="no_all_uppercase" name="no_all_uppercase" {'checked' if self.config['clues']['no_all_uppercase'] else ''}>
                                   <label for="no_all_uppercase" style="display: inline;">前12位不能全是大写</label>
                               </div>

                               <div class="form-group">
                                   <label>自适应配置:</label><br>
                                   <input type="number" id="adaptive_small_space_threshold" name="adaptive_small_space_threshold" 
                                          value="{self.config['adaptive_config']['small_space_threshold']}" style="width: 150px;">
                                   <label for="adaptive_small_space_threshold" style="display: inline;">小空间阈值</label><br>

                                   <input type="number" id="adaptive_medium_space_threshold" name="adaptive_medium_space_threshold" 
                                          value="{self.config['adaptive_config']['medium_space_threshold']}" style="width: 150px;">
                                   <label for="adaptive_medium_space_threshold" style="display: inline;">中等空间阈值</label><br>

                                   <input type="number" id="adaptive_rotation_interval_hours" name="adaptive_rotation_interval_hours" 
                                          value="{self.config['adaptive_config']['rotation_interval_hours']}" style="width: 150px;">
                                   <label for="adaptive_rotation_interval_hours" style="display: inline;">种子轮换间隔(小时)</label><br>

                                   <input type="number" id="adaptive_max_attempts_no_result" name="adaptive_max_attempts_no_result" 
                                          value="{self.config['adaptive_config']['max_attempts_no_result']}" style="width: 150px;">
                                   <label for="adaptive_max_attempts_no_result" style="display: inline;">无结果最大尝试数</label>
                               </div>

                               <button type="button" onclick="updateConfig()">💾 更新配置</button>
                           </form>
                       </div>

                       <div class="config-section">
                           <h2>🖥️ 节点分配信息</h2>
                           <table class="node-table">
                               <thead>
                                   <tr>
                                       <th>节点ID</th>
                                       <th>IP地址</th>
                                       <th>分区种子</th>
                                       <th>注册时间</th>
                                       <th>序号</th>
                                       <th>在线时长</th>
                                       <th>总尝试次数</th>
                                   </tr>
                               </thead>
                               <tbody>
                                   {node_rows}
                               </tbody>
                           </table>
                       </div>

                       <div class="config-section">
                           <h2>🔧 系统信息</h2>
                           <p><strong>当前配置版本:</strong> {self.config.get('version', '1.0')}</p>
                           <p><strong>配置文件:</strong> {MASTER_CONFIG_FILE}</p>
                           <p><strong>进度文件:</strong> {DISTRIBUTED_PROGRESS_FILE}</p>
                           <p><strong>WIF记录:</strong> {FOUND_WIFS_FILE}</p>
                           <p><strong>监控面板:</strong> <a href="/status" target="_blank">打开监控面板</a></p>
                           <p><strong>节点统计:</strong> <a href="/node_stats" target="_blank">查看详细统计</a></p>
                       </div>
                   </div>
               </body>
               </html>
               """



        if not node_rows:
            node_rows = '<tr><td colspan="7" style="text-align: center; color: #999;">暂无节点注册</td></tr>'

        search_space_info = self._calculate_search_space_info()

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>WIF集群管理</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
                .config-section {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                .form-group {{ margin-bottom: 15px; }}
                label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
                input[type="text"], textarea, select {{ 
                    width: 100%; 
                    padding: 8px; 
                    border: 1px solid #ddd; 
                    border-radius: 4px; 
                    box-sizing: border-box;
                }}
                textarea {{ height: 100px; resize: vertical; }}
                button {{ 
                    background: #3498db; 
                    color: white; 
                    padding: 10px 20px; 
                    border: none; 
                    border-radius: 5px; 
                    cursor: pointer; 
                    font-size: 16px;
                }}
                button:hover {{ background: #2980b9; }}
                .node-table {{ width: 100%; border-collapse: collapse; }}
                .node-table th, .node-table td {{ 
                    padding: 10px; 
                    text-align: left; 
                    border-bottom: 1px solid #ddd; 
                }}
                .node-table th {{ background: #f8f9fa; }}
                .success-message {{ 
                    background: #d4edda; 
                    color: #155724; 
                    padding: 10px; 
                    border-radius: 4px; 
                    margin: 10px 0;
                }}
                .info-card {{ background: #e8f4fd; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            </style>
            <script>
                function updateConfig() {{
                    const form = document.getElementById('configForm');
                    const formData = new FormData(form);
                    const data = Object.fromEntries(formData);

                    fetch('/update_config', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify(data)
                    }})
                    .then(response => response.json())
                    .then(result => {{
                        const messageDiv = document.getElementById('message');
                        messageDiv.innerHTML = '<div class="success-message">✅ 配置更新成功！所有节点将在下次请求时获取新配置。</div>';
                        setTimeout(() => messageDiv.innerHTML = '', 3000);
                    }})
                    .catch(error => {{
                        console.error('Error:', error);
                    }});
                }}

                function updateTemplate() {{
                    const template = document.getElementById('template_wif').value;
                    const questionCount = (template.match(/\?/g) || []).length;
                    document.getElementById('position_count').value = questionCount;
                }}
            </script>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎯 WIF搜索集群管理系统</h1>
                    <p>自适应搜索策略 - 主节点控制面板</p>
                </div>

                <div id="message"></div>

                <div class="config-section">
                    <h2>📊 搜索空间分析</h2>
                    <div class="info-card">
                        <p><strong>空间类型:</strong> {search_space_info['space_type'].upper()}</p>
                        <p><strong>总组合数:</strong> {search_space_info['total_combinations']:,}</p>
                        <p><strong>可变位置:</strong> {search_space_info['variable_positions']}</p>
                        <p><strong>推荐策略:</strong> {search_space_info['description']}</p>
                    </div>
                </div>

                <!-- 配置表单部分保持不变，省略以节省空间 -->
                <!-- ... 配置表单HTML代码 ... -->

            </div>
        </body>
        </html>
        """

    def _generate_status_page(self, progress, found_wifs):
        """生成状态页面"""
        active_count = self._count_active_nodes(progress['nodes'])
        coverage = self._calculate_coverage(progress['nodes'])
        search_space_info = self._calculate_search_space_info()
        total_stats = self._calculate_total_stats(progress['nodes'])

        node_rows = ""
        now = time.time()
        for node_id, node_data in sorted(progress['nodes'].items(),
                                         key=lambda x: x[1].get('total_attempts', 0),
                                         reverse=True):
            last_update = node_data['last_update']
            time_diff = now - last_update
            if time_diff < 300:
                status = "🟢 活跃"
                status_class = "active"
            elif time_diff < 1800:
                status = "🟡 闲置"
                status_class = "inactive"
            else:
                status = "🔴 离线"
                status_class = "inactive"

            online_duration = node_data.get('online_duration', 0)
            total_attempts = node_data.get('total_attempts', 0)
            speed = total_attempts / online_duration if online_duration > 0 else 0

            node_rows += f"""
            <tr>
                <td>{node_id}</td>
                <td>{node_data.get('ip_address', 'N/A')}</td>
                <td>{node_data['tested_count']:,}</td>
                <td class="found">{node_data['found_count']}</td>
                <td>{total_attempts:,}</td>
                <td>{self._format_duration(online_duration)}</td>
                <td>{speed:.1f}/秒</td>
                <td class="partition">{node_data.get('partition_seed', 'N/A')[:16]}...</td>
                <td>{datetime.fromtimestamp(last_update).strftime('%H:%M:%S')}</td>
                <td class="{status_class}">{status}</td>
            </tr>
            """

        if not node_rows:
            node_rows = '<tr><td colspan="10">暂无节点数据</td></tr>'

        found_section = ""
        if not found_wifs:
            found_section = '<div style="text-align: center; padding: 40px; color: #7f8c8d;">🔍 尚未找到有效WIF，继续搜索中...</div>'
        else:
            for i, wif_data in enumerate(reversed(found_wifs), 1):
                found_section += f"""
                <div style="background: #d4edda; margin: 10px 0; padding: 15px; border-radius: 5px; border: 1px solid #c3e6cb;">
                    <h4>🎉 第 {wif_data['found_count']} 个有效WIF</h4>
                    <p><strong>发现节点:</strong> {wif_data['node_id']}</p>
                    <p><strong>发现时间:</strong> {wif_data['timestamp']}</p>
                    <p><strong>WIF地址:</strong> <code style="background: #f8f9fa; padding: 5px; border-radius: 3px;">{wif_data['wif']}</code></p>
                    <p><strong>私钥(HEX):</strong> <code style="background: #f8f9fa; padding: 5px; border-radius: 3px;">{wif_data['private_key']}</code></p>
                    <p><strong>压缩格式:</strong> {'是' if wif_data['compressed'] else '否'}</p>
                </div>
                """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>WIF搜索集群监控</title>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .container {{ max-width: 1600px; margin: 0 auto; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 10px; }}
                .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin: 20px 0; }}
                .stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .nodes-table, .found-table {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 20px 0; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; }}
                .found {{ color: #e74c3c; font-weight: bold; }}
                .active {{ color: #27ae60; }}
                .inactive {{ color: #95a5a6; }}
                .partition {{ font-family: monospace; font-size: 12px; }}
                .space-info {{ background: #e8f4fd; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎯 WIF搜索集群监控 (自适应搜索模式)</h1>
                    <p>更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 自动刷新: 每10秒</p>
                </div>

                <div class="space-info">
                    <h3>🔍 搜索空间分析</h3>
                    <p><strong>空间类型:</strong> {search_space_info['space_type'].upper()} | 
                       <strong>总组合数:</strong> {search_space_info['total_combinations']:,} | 
                       <strong>策略:</strong> {search_space_info['description']}</p>
                </div>

                <div class="stats">
                    <div class="stat-card">
                        <h3>📊 全局统计</h3>
                        <p><strong>总尝试次数:</strong> {progress['total_tested']:,}</p>
                        <p><strong>找到WIF数量:</strong> <span class="found">{progress['total_found']}</span></p>
                        <p><strong>搜索效率:</strong> {self._calculate_efficiency(progress['total_tested'], progress['total_found'])}</p>
                    </div>
                    <div class="stat-card">
                        <h3>🖥️ 节点状态</h3>
                        <p><strong>注册节点:</strong> {len(progress['nodes'])}</p>
                        <p><strong>活跃节点:</strong> <span class="active">{active_count}</span></p>
                        <p><strong>目标节点:</strong> {self.config['total_nodes']}</p>
                    </div>
                    <div class="stat-card">
                        <h3>⚡ 性能统计</h3>
                        <p><strong>总在线时长:</strong> {self._format_duration(total_stats['total_online_time'])}</p>
                        <p><strong>总尝试次数:</strong> {total_stats['total_attempts']:,}</p>
                        <p><strong>平均速度:</strong> {total_stats['avg_speed_per_second']:.1f}/秒</p>
                    </div>
                    <div class="stat-card">
                        <h3>🔧 配置信息</h3>
                        <p><strong>模板WIF:</strong> {self.config['template_wif'][:20]}...</p>
                        <p><strong>可变位置:</strong> {len(self.config['position_candidates'])}</p>
                        <p><strong>运行时间:</strong> {self._format_duration(progress.get('start_time', time.time()))}</p>
                    </div>
                </div>

                <div class="nodes-table">
                    <h3>🖥️ 节点工作状态 (按总尝试次数排序)</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>节点ID</th>
                                <th>IP地址</th>
                                <th>当前尝试</th>
                                <th>找到数量</th>
                                <th>总尝试次数</th>
                                <th>在线时长</th>
                                <th>平均速度</th>
                                <th>分区种子</th>
                                <th>最后报告</th>
                                <th>状态</th>
                            </tr>
                        </thead>
                        <tbody>
                            {node_rows}
                        </tbody>
                    </table>
                </div>

                <div class="found-table">
                    <h3>💰 找到的WIF记录 ({len(found_wifs)} 个)</h3>
                    {found_section}
                </div>
            </div>
        </body>
        </html>
        """

    def _count_active_nodes(self, nodes):
        """计算活跃节点数"""
        now = time.time()
        return sum(1 for node in nodes.values() if now - node['last_update'] < 300)

    def _calculate_coverage(self, nodes):
        """计算搜索覆盖范围"""
        unique_seeds = len(set(node.get('partition_seed', '') for node in nodes.values()))
        total_nodes = self.config.get('total_nodes', 50)

        if isinstance(total_nodes, str):
            try:
                total_nodes = int(total_nodes)
            except:
                total_nodes = 50

        if total_nodes > 0:
            coverage = (unique_seeds / total_nodes) * 100
        else:
            coverage = 0

        return round(coverage, 1)

    def _calculate_efficiency(self, tested, found):
        """计算搜索效率"""
        if found == 0:
            return "计算中..."
        efficiency = tested / found
        if efficiency > 1000000:
            return f"{efficiency / 1000000:.1f}M 次/个"
        elif efficiency > 1000:
            return f"{efficiency / 1000:.1f}K 次/个"
        else:
            return f"{efficiency:.0f} 次/个"

    def _format_duration(self, duration_seconds):
        """格式化运行时间"""
        if duration_seconds is None or duration_seconds < 1:
            return "0秒"
        elif duration_seconds < 60:
            return f"{int(duration_seconds)}秒"
        elif duration_seconds < 3600:
            minutes = int(duration_seconds / 60)
            seconds = int(duration_seconds % 60)
            return f"{minutes}分钟{seconds}秒"
        elif duration_seconds < 86400:
            hours = int(duration_seconds / 3600)
            minutes = int((duration_seconds % 3600) / 60)
            return f"{hours}小时{minutes}分钟"
        else:
            days = int(duration_seconds / 86400)
            hours = int((duration_seconds % 86400) / 3600)
            return f"{days}天{hours}小时"

    def load_progress(self):
        """加载分布式进度"""
        try:
            with open(DISTRIBUTED_PROGRESS_FILE, 'r') as f:
                progress = json.load(f)
                if 'start_time' not in progress:
                    progress['start_time'] = time.time()
                return progress
        except:
            return {
                'nodes': {},
                'total_tested': 0,
                'total_found': 0,
                'last_updated': time.time(),
                'start_time': time.time()
            }

    def save_progress(self, progress):
        """保存分布式进度"""
        try:
            with open(DISTRIBUTED_PROGRESS_FILE, 'w') as f:
                json.dump(progress, f, indent=2)
        except Exception as e:
            print(f"{Colors.RED}❌ 保存进度失败: {e}{Colors.END}")

    def load_found_wifs(self):
        """加载找到的WIF记录"""
        try:
            with open(FOUND_WIFS_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                wifs = []
                sections = content.split('=' * 50)
                for section in sections:
                    if '找到第' in section and '有效WIF' in section:
                        lines = section.strip().split('\n')
                        wif_data = {}
                        for line in lines:
                            if '找到第' in line and '个有效WIF' in line:
                                wif_data['found_count'] = int(line.split('第')[1].split('个')[0])
                            elif '时间:' in line:
                                wif_data['timestamp'] = line.split('时间: ')[1].strip()
                            elif '节点:' in line:
                                wif_data['node_id'] = line.split('节点: ')[1].strip()
                            elif 'WIF:' in line:
                                wif_data['wif'] = line.split('WIF: ')[1].strip()
                            elif '私钥:' in line:
                                wif_data['private_key'] = line.split('私钥: ')[1].strip()
                            elif '压缩:' in line:
                                wif_data['compressed'] = line.split('压缩: ')[1].strip() == '是'
                        if wif_data:
                            wifs.append(wif_data)
                return wifs
        except:
            return []

    def save_found_wif(self, wif, private_key, compressed, node_id, found_count):
        """保存找到的WIF"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(FOUND_WIFS_FILE, 'a', encoding='utf-8') as f:
                f.write(f"=== 找到第{found_count}个有效WIF ===\n")
                f.write(f"时间: {timestamp}\n")
                f.write(f"节点: {node_id}\n")
                f.write(f"WIF: {wif}\n")
                f.write(f"私钥: {private_key}\n")
                f.write(f"压缩: {'是' if compressed else '否'}\n")
                f.write("=" * 50 + "\n\n")

            progress = self.load_progress()
            progress['total_found'] = found_count
            self.save_progress(progress)

        except Exception as e:
            print(f"{Colors.RED}❌ 保存WIF记录失败: {e}{Colors.END}")


def display_cluster_info(host, port):
    """显示集群信息"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}           WIF搜索集群 - 自适应搜索模式{Colors.END}")
    print(f"{Colors.CYAN}{'=' * 70}{Colors.END}")
    print(f"{Colors.GREEN}🎯 主节点服务{Colors.END}")
    print(f"  {Colors.WHITE}• 监听地址:{Colors.END} {Colors.BOLD}{host}:{port}{Colors.END}")
    print(
        f"  {Colors.WHITE}• 启动时间:{Colors.END} {Colors.BOLD}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    print(f"\n{Colors.GREEN}📊 监控地址{Colors.END}")
    print(f"  {Colors.WHITE}• 网页面板:{Colors.END} {Colors.BOLD}http://{host}:{port}/status{Colors.END}")
    print(f"  {Colors.WHITE}• 管理界面:{Colors.END} {Colors.BOLD}http://{host}:{port}/admin{Colors.END}")
    print(f"  {Colors.WHITE}• 节点统计:{Colors.END} {Colors.BOLD}http://{host}:{port}/node_stats{Colors.END}")
    print(f"\n{Colors.GREEN}🎯 自适应策略{Colors.END}")
    print(f"  {Colors.WHITE}• 小空间:{Colors.END} {Colors.BOLD}顺序分区搜索{Colors.END}")
    print(f"  {Colors.WHITE}• 中等空间:{Colors.END} {Colors.BOLD}记忆随机搜索{Colors.END}")
    print(f"  {Colors.WHITE}• 大空间:{Colors.END} {Colors.BOLD}轮换随机搜索{Colors.END}")
    print(f"\n{Colors.YELLOW}等待节点连接...{Colors.END}")


def run_master_server(host='0.0.0.0', port=8888):
    """运行主节点服务器"""
    display_cluster_info(host, port)

    # 使用线程化服务器而不是普通HTTPServer
    server = ThreadedHTTPServer((host, port), MasterRequestHandler)

    # 设置socket选项
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

    print(f"{Colors.GREEN}🚀 启动线程化主节点服务器{Colors.END}")
    print(f"{Colors.CYAN}📡 服务器配置:{Colors.END}")
    print(f"  {Colors.WHITE}• 监听地址:{Colors.END} {Colors.BOLD}{host}:{port}{Colors.END}")
    print(f"  {Colors.WHITE}• 连接超时:{Colors.END} {Colors.BOLD}{server.timeout}秒{Colors.END}")
    print(f"  {Colors.WHITE}• 守护线程:{Colors.END} {Colors.BOLD}{server.daemon_threads}{Colors.END}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}🛑 停止主节点服务器{Colors.END}")
        server.shutdown()
    except Exception as e:
        print(f"\n{Colors.RED}❌ 服务器错误: {e}{Colors.END}")


if __name__ == "__main__":
    run_master_server()