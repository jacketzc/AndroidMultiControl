import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import re
import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os
from PIL import Image, ImageTk
import tempfile

global_workers = 16

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("手机批量工具")
        self.root.geometry("700x600")  # 增加窗口高度以容纳扫描结果
        # 配置网格权重，确保内容区可以扩展，而底部按钮固定
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # 存储所有手机（从ADB获取）
        self.phones = []
        self.selected_phones = []  # 当前选中的手机
        self.check_vars = {}  # 用于存储复选框变量
        self.thumbnail_labels = {}  # 存储设备ID到其缩略图Label组件的映射
        self.thumbnails_loading_status = {}  # 存储每个设备的缩略图加载状态
        self.thumbnail_size = (100, 100)  # 定义缩略图尺寸
        self.thumbnails_loaded = False  # 新增标志位，记录缩略图是否已加载

        # 主内容区容器
        self.main_container = tk.Frame(root)
        self.main_container.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        # 主内容区 - 使用Canvas和Scrollbar创建可滚动区域
        self.canvas_frame = tk.Frame(self.main_container)
        self.canvas_frame.grid(row=0, column=0, sticky="nsew")

        self.canvas = tk.Canvas(self.canvas_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)

        # 将滚动区域绑定到Canvas
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # self.canvas_frame1 = tk.Frame(self.main_container)
        # self.canvas1 = tk.Canvas(self.canvas_frame1, highlightthickness=0)
        # self.scrollbar1 = ttk.Scrollbar(self.canvas_frame1, orient="vertical", command=self.canvas1.yview)
        # self.scrollable_frame1 = tk.Frame(self.canvas1)
        # self.scrollable_frame1.bind(
        #     "<Configure>",
        #     lambda e: self.canvas1.configure(scrollregion=self.canvas1.bbox("all"))
        # )


        # 在Canvas上创建窗口，将滚动框架放入其中
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # 布局Canvas和Scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 绑定鼠标滚轮事件到Canvas
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel_linux_up)
        self.canvas.bind("<Button-5>", self._on_mousewheel_linux_down)

        # 底部菜单栏（固定高度）
        self.bottom_frame = tk.Frame(root, height=60, bg="lightgray")  # 可选背景色便于区分
        self.bottom_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        # 防止底部框架因内容挤压而收缩
        self.bottom_frame.grid_propagate(False)

        # 修改按钮名称
        self.btn1 = tk.Button(self.bottom_frame, text="手机列表", command=self.show_phones_and_thumbnails)
        self.btn1.pack(side=tk.LEFT, padx=10, pady=10)

        self.btn2 = tk.Button(self.bottom_frame, text="批量工具", command=self.show_tools)
        self.btn2.pack(side=tk.LEFT, padx=10, pady=10)

        # # 初始就显示手机列表页面以及缩略图
        self.show_phones_and_thumbnails()

    def _on_mousewheel(self, event):
        """处理鼠标滚轮事件 (Windows)"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux_up(self, event):
        """处理鼠标滚轮向上事件 (Linux)"""
        self.canvas.yview_scroll(-1, "units")

    def _on_mousewheel_linux_down(self, event):
        """处理鼠标滚轮向下事件 (Linux)"""
        self.canvas.yview_scroll(1, "units")

    def clear_content(self):
        """清空滚动内容区"""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        # 清空缩略图Label映射和状态
        self.thumbnail_labels.clear()
        self.thumbnails_loading_status.clear()
        self.thumbnails_loaded = False  # 清空内容时重置标志位

    def is_valid_ip_port(self, input_str):
        """校验输入是否为有效的IP:端口格式"""
        # 正则表达式匹配 IP:端口 格式
        pattern = r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$'
        match = re.match(pattern, input_str)
        if not match:
            return False

        ip, port = match.groups()
        # 检查IP地址各段是否在0-255范围内
        ip_parts = ip.split('.')
        for part in ip_parts:
            if not 0 <= int(part) <= 255:
                return False
        # 检查端口是否在有效范围内
        port_int = int(port)
        if not 1 <= port_int <= 65535:
            return False

        return True

    def is_valid_network(self, input_str):
        """校验输入是否为有效的网段格式 (CIDR)"""
        try:
            ipaddress.IPv4Network(input_str, strict=False)
            return True
        except ValueError:
            return False

    def run_adb_connect(self, ip_port):
        """执行adb connect命令"""
        try:
            result = subprocess.run(['adb', 'connect', ip_port], capture_output=True, text=True, timeout=1)  # 超时改为2秒
            output = result.stdout.strip()
            if "connected" in output:
                return True, output
            else:
                return False, output
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip() if e.stderr else "连接失败"
        except subprocess.TimeoutExpired:
            return False, f"连接 {ip_port} 超时"
        except FileNotFoundError:
            return False, "未找到 'adb' 命令，请确保ADB已安装并添加到系统PATH中。"

    def run_adb_disconnect(self, ip_port):
        """执行adb disconnect命令"""
        try:
            result = subprocess.run(['adb', 'disconnect', ip_port], capture_output=True, text=True, check=True)
            output = result.stdout.strip()
            return True, output
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip() if e.stderr else "断开连接失败"
        except FileNotFoundError:
            return False, "未找到 'adb' 命令，请确保ADB已安装并添加到系统PATH中。"

    def run_adb_devices(self):
        """执行adb devices命令并返回设备列表"""
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, check=True)
            output = result.stdout
            # 解析输出，提取设备列表
            lines = output.strip().split('\n')[1:]  # 跳过第一行 "List of devices attached"
            devices = []
            for line in lines:
                if line.strip() and not line.startswith('*'):
                    match = re.match(r'(\S+)\s+device', line)
                    if match:
                        device_id = match.group(1)
                        devices.append(device_id)
            return devices
        except subprocess.CalledProcessError:
            messagebox.showerror("错误", "执行 'adb devices' 失败，请检查ADB是否安装并正确配置。")
            return []
        except FileNotFoundError:
            messagebox.showerror("错误", "未找到 'adb' 命令，请确保ADB已安装并添加到系统PATH中。")
            return []

    def connect_and_refresh(self):
        """连接设备并刷新页面"""
        ip_port = self.ip_port_entry.get().strip()
        if not ip_port:
            messagebox.showwarning("警告", "请输入IP和端口！")
            return

        if not self.is_valid_ip_port(ip_port):
            messagebox.showerror("错误", "输入的IP:端口格式不正确！\n例如: 192.168.1.100:5555")
            return

        success, message = self.run_adb_connect(ip_port)
        if success:
            messagebox.showinfo("成功", f"连接成功！\n{message}")
            # 清空输入框
            self.ip_port_entry.delete(0, tk.END)
            # 重新加载手机列表
            self.show_phones_and_thumbnails()
        else:
            messagebox.showerror("连接失败", f"{message}")

    def scan_network(self):
        """扫描网段并连接设备"""
        network_str = self.network_entry.get().strip()
        if not network_str:
            messagebox.showwarning("警告", "请输入网段！")
            return

        if not self.is_valid_network(network_str):
            messagebox.showerror("错误", "输入的网段格式不正确！\n例如: 192.168.1.0/24")
            return

        try:
            network = ipaddress.IPv4Network(network_str, strict=False)
            ips = [str(ip) for ip in network.hosts()]
        except Exception as e:
            messagebox.showerror("错误", f"解析网段时出错: {e}")
            return

        # 在UI上显示扫描进度和日志
        self.clear_content()

        progress_label = tk.Label(self.scrollable_frame, text="正在扫描网段并连接设备 (多线程) ...", font=("Arial", 12))
        progress_label.pack(pady=10)

        # 创建一个文本框用于显示扫描日志
        log_text = scrolledtext.ScrolledText(self.scrollable_frame, height=15, width=80, state=tk.DISABLED)
        log_text.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # 启动后台线程执行扫描和连接
        thread = threading.Thread(target=self._perform_scan_and_connect, args=(ips, log_text))
        thread.start()

    def _perform_scan_and_connect(self, ips, log_text_widget):
        """在后台线程中执行扫描和连接操作，使用多线程"""
        connected_devices = []
        max_workers = global_workers

        # 使用ThreadPoolExecutor管理线程池
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务到线程池
            future_to_ip = {executor.submit(self._try_connect_single_ip, ip): ip for ip in ips}

            # 遍历已完成的任务
            for future in as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    success, message, ip_port = future.result()
                    if success:
                        connected_devices.append(ip_port)
                        log_message = f"成功连接: {ip_port}\n"
                    else:
                        log_message = f"连接失败: {ip_port}, 原因: {message}\n"

                    # 在UI线程中更新日志
                    self.root.after(0, self._append_log, log_text_widget, log_message)

                except Exception as exc:
                    log_message = f"扫描IP {ip} 时发生异常: {exc}\n"
                    self.root.after(0, self._append_log, log_text_widget, log_message)

        # 扫描完成后，在主线程中更新UI
        self.root.after(0, self._on_scan_complete, connected_devices)

    def _try_connect_single_ip(self, ip):
        """尝试连接单个IP，供线程池调用"""
        adb_port = "5555"
        ip_port = f"{ip}:{adb_port}"
        success, message = self.run_adb_connect(ip_port)
        return success, message, ip_port

    def _append_log(self, log_widget, message):
        """辅助函数，在日志文本框中追加信息"""
        log_widget.config(state=tk.NORMAL)
        log_widget.insert(tk.END, message)
        log_widget.see(tk.END)  # 滚动到底部
        log_widget.config(state=tk.DISABLED)

    def _on_scan_complete(self, connected_devices):
        """扫描完成后的UI更新"""
        # 重新加载手机列表
        self.show_phones_and_thumbnails()  # 直接调用，不再使用延时
        # 清空输入框
        self.network_entry.delete(0, tk.END)
        if connected_devices:
            summary_message = f"\n\n扫描完成！成功连接 {len(connected_devices)} 个设备:\n" + "\n".join(connected_devices)
            messagebox.showinfo("扫描结果", summary_message)
        else:
            messagebox.showinfo("扫描结果", "扫描完成，未发现可连接的设备。")

    def capture_screenshot(self, device_id):
        """为指定设备截取屏幕截图并返回PIL Image对象"""
        try:
            # 创建临时文件
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_filename = temp_file.name
            temp_file.close()  # 关闭文件句柄，允许adb写入

            # 执行adb命令抓取截图
            result = subprocess.run(['adb', '-s', device_id, 'exec-out', 'screencap', '-p'],
                                    stdout=open(temp_filename, 'wb'),
                                    stderr=subprocess.PIPE,
                                    check=True)

            # 打开临时文件并转换为PIL Image
            image = Image.open(temp_filename)
            # 删除临时文件
            os.unlink(temp_filename)
            return image
        except subprocess.CalledProcessError as e:
            print(f"截图失败 for {device_id}: {e.stderr.decode()}")
            # 删除可能已创建的临时文件
            try:
                os.unlink(temp_filename)
            except:
                pass
            return None
        except Exception as e:
            print(f"处理截图时出错 for {device_id}: {e}")
            # 删除可能已创建的临时文件
            try:
                os.unlink(temp_filename)
            except:
                pass
            return None

    def resize_image_to_thumbnail(self, pil_image, size=None):
        """将PIL图像调整大小为指定尺寸的缩略图，并保持宽高比"""
        if size is None:
            size = self.thumbnail_size
        if pil_image:
            original_width, original_height = pil_image.size
            target_width, target_height = size

            # 计算缩放比例，保持原始宽高比
            ratio = min(target_width / original_width, target_height / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)

            resized_image = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 创建一个新的RGBA图像，尺寸为指定的缩略图尺寸
            final_image = Image.new("RGBA", size, (255, 255, 255, 0))  # 白色背景或透明背景

            # 计算粘贴位置，使其居中
            paste_x = (target_width - new_width) // 2
            paste_y = (target_height - new_height) // 2

            # 将缩放后的图像粘贴到新图像上
            final_image.paste(resized_image, (paste_x, paste_y))

            return final_image
        return None

    def update_thumbnails(self):
        """更新所有设备的缩略图（使用多线程），获取到后立即渲染"""
        # 初始化加载状态
        for device_id in self.phones:
            self.thumbnails_loading_status[device_id] = "loading"
            # 更新对应设备的文本标签为“获取中...”
            if device_id in self.check_vars:
                checkbox_widget = None
                for widget in self.scrollable_frame.winfo_children():
                    if isinstance(widget, tk.Frame):
                        for child in widget.winfo_children():
                            if isinstance(child, tk.Checkbutton) and child.cget("text").startswith(device_id):
                                checkbox_widget = child
                                break
                        if checkbox_widget:
                            break
                if checkbox_widget:
                    checkbox_widget.config(text=f"{device_id} (获取中...)")
                    self.root.update_idletasks()  # 刷新UI

        max_workers = 8  # 设置线程池大小为8

        def _update_in_thread_pool():
            # 使用ThreadPoolExecutor管理线程池
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有截图任务到线程池
                future_to_device = {executor.submit(self._capture_and_resize_single, device_id): device_id for device_id
                                    in self.phones}

                # 遍历已完成的任务
                for future in as_completed(future_to_device):
                    device_id = future_to_device[future]
                    try:
                        thumbnail_img = future.result()
                        # 存储到缓存
                        if thumbnail_img:
                            self.thumbnails_loading_status[device_id] = "loaded"
                        else:
                            # 如果截图失败，可以考虑存一个默认图标或None
                            self.thumbnails_loading_status[device_id] = "failed"

                        # 在主线程中更新UI显示单个设备的缩略图
                        self.root.after(0, self._update_single_thumbnail_ui, device_id, thumbnail_img)

                    except Exception as exc:
                        print(f'设备 {device_id} 处理缩略图时发生异常: {exc}')
                        self.thumbnails_loading_status[device_id] = "failed"
                        # 在主线程中更新UI显示单个设备的缩略图失败
                        self.root.after(0, self._update_single_thumbnail_ui, device_id, None)

        # 在后台线程中启动线程池
        thread = threading.Thread(target=_update_in_thread_pool)
        thread.start()
        self.thumbnails_loaded = True  # 标记缩略图已请求加载

    def _capture_and_resize_single(self, device_id):
        """为单个设备截图并缩放（供线程池调用）"""
        # 1. 截图
        screenshot_img = self.capture_screenshot(device_id)
        # 2. 缩放
        thumbnail_img = self.resize_image_to_thumbnail(screenshot_img)
        return thumbnail_img

    def _update_single_thumbnail_ui(self, device_id, thumbnail_img):
        """更新单个设备的UI缩略图显示"""
        # 1. 更新复选框文本，移除“获取中...”标记
        checkbox_widget = None
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Checkbutton) and child.cget("text").startswith(device_id):
                        original_text = device_id
                        if " (获取中...)" in child.cget("text"):
                            original_text = child.cget("text").replace(" (获取中...)", "")
                        child.config(text=original_text)
                        break
                if checkbox_widget:
                    break

        # 2. 更新对应的缩略图Label
        if device_id in self.thumbnail_labels:
            label_widget = self.thumbnail_labels[device_id]
            if thumbnail_img:
                # 将PIL图像转换为Tkinter PhotoImage
                photo = ImageTk.PhotoImage(thumbnail_img)
                label_widget.config(image=photo, text="", width=self.thumbnail_size[0],
                                    height=self.thumbnail_size[1])  # 设置固定宽高
                label_widget.image = photo  # 保持引用，防止被垃圾回收
                label_widget.grid()  # 确保Label可见
            else:
                # 如果没有缩略图，隐藏Label，只显示复选框
                label_widget.config(image="", text="", width=1, height=1)  # 设置为最小尺寸
                label_widget.grid_remove()  # 隐藏Label，不占用空间

    def show_phones_and_thumbnails(self):
        self.show_phones()
        self.update_thumbnails()

    def show_phones(self):
        """回到首页，不刷新页面"""
        self.clear_content()

        # 添加IP:端口输入区域 - 使用 pack 布局，并调整 pady
        input_frame = tk.Frame(self.scrollable_frame)
        input_frame.pack(fill=tk.X, padx=10, pady=(5, 1))  # 修改 pady 为 (5, 1)

        tk.Label(input_frame, text="IP:端口(比如192.168.100.1)").pack(side=tk.LEFT)
        self.ip_port_entry = tk.Entry(input_frame, width=20)
        self.ip_port_entry.pack(side=tk.LEFT, padx=27)
        connect_btn = tk.Button(input_frame, text="连接", command=self.connect_and_refresh)
        connect_btn.pack(side=tk.LEFT, padx=0)


        # 添加网段扫描输入区域 - 使用 pack 布局，并调整 pady
        scan_frame = tk.Frame(self.scrollable_frame)
        scan_frame.pack(fill=tk.X, padx=10, pady=(1, 2))  # 修改 pady 为 (1, 2)

        tk.Label(scan_frame, text="网段扫描(比如192.168.66.0/24)").pack(side=tk.LEFT)
        self.network_entry = tk.Entry(scan_frame, width=20)
        self.network_entry.pack(side=tk.LEFT, padx=5)
        scan_btn = tk.Button(scan_frame, text="扫描", command=self.scan_network)
        scan_btn.pack(side=tk.LEFT, padx=22)

        # 添加全选按钮 - 使用 pack 布局，并调整 pady
        select_all_frame = tk.Frame(self.scrollable_frame)
        select_all_frame.pack(fill=tk.X, padx=10, pady=2)  # 修改 pady 为 2

        # 定义全选/取消全选的函数
        def select_all():
            for var in self.check_vars.values():
                var.set(True)

        def unselect_all():
            for var in self.check_vars.values():
                var.set(False)

        # 创建全选按钮
        select_all_button = tk.Button(select_all_frame, text="全选", command=select_all)
        select_all_button.pack(side=tk.LEFT, padx=(0, 5))

        # 创建取消全选按钮
        unselect_all_button = tk.Button(select_all_frame, text="取消全选", command=unselect_all)
        unselect_all_button.pack(side=tk.LEFT)

        # # 添加展示缩略图按钮，放在取消全选按钮后面
        # show_thumbnails_btn = tk.Button(select_all_frame, text="展示缩略图", command=self.update_thumbnails)
        # show_thumbnails_btn.pack(side=tk.LEFT, padx=5)

        # 执行adb命令获取设备列表
        adb_devices = self.run_adb_devices()
        if not adb_devices:
            tk.Label(self.scrollable_frame, text="未检测到已连接的设备", font=("Arial", 12), fg="red").pack(expand=True,
                                                                                                            pady=10)
            return

        # 更新内部存储的手机列表
        self.phones = adb_devices
        # 清空旧的复选框变量
        self.check_vars = {}

        # 创建列表标题
        tk.Label(self.scrollable_frame, text="请选择手机：", font=("Arial", 10, "bold")).pack(anchor="w", pady=(10, 0))

        # 加载设备列表时，根据缩略图是否已加载来决定布局
        for phone in self.phones:
            item_frame = tk.Frame(self.scrollable_frame)
            item_frame.pack(fill=tk.X, padx=20, pady=1)  # 修改 pady 为 1

            var = tk.BooleanVar()
            cb = tk.Checkbutton(item_frame, text=phone, variable=var)
            cb.grid(row=0, column=0, sticky="w")  # 使用grid布局
            self.check_vars[phone] = var

            # 创建一个Label用于显示缩略图或占位符
            # 如果缩略图已加载过，则显示它；否则，初始隐藏且尺寸最小
            thumb_label = tk.Label(item_frame, text="", width=1, height=1)  # 设置为最小尺寸
            thumb_label.grid(row=0, column=1, padx=(10, 0), sticky="w")  # 使用grid布局
            if self.thumbnails_loaded and phone in self.thumbnails_loading_status:
                # 如果缩略图曾经加载过，尝试恢复其状态
                status = self.thumbnails_loading_status[phone]
                if status == "loaded" and phone in self.thumbnail_labels and self.thumbnail_labels[phone].image:
                    # 如果之前加载成功且有图片缓存，则显示
                    thumb_label.config(image=self.thumbnail_labels[phone].image, width=self.thumbnail_size[0],
                                       height=self.thumbnail_size[1])
                    thumb_label.grid()  # 显示Label
                else:
                    # 否则保持隐藏
                    thumb_label.grid_remove()
            else:
                # 如果缩略图从未加载过，初始隐藏
                thumb_label.grid_remove()

            # 将Label组件存储起来，方便后续更新
            self.thumbnail_labels[phone] = thumb_label

    def show_tools(self):
        """显示工具按钮"""
        self.clear_content()

        # 重置滚动条位置
        self.canvas.yview_moveto(0)  # 移动到顶部

        tk.Label(self.scrollable_frame, text="可用工具", font=("Arial", 12, "bold")).pack(anchor="w", pady=5)

        tools = [
            ("scrcpy", self.run_scrcpy_for_selected),
            ("断开连接", self.disconnect_selected),
        ]

        for name, func in tools:
            btn = tk.Button(self.scrollable_frame, text=name, command=lambda f=func: f())
            btn.pack(pady=5)

    def get_selected_phones(self):
        """获取当前选中的手机列表"""
        selected = [phone for phone, var in self.check_vars.items() if var.get()]
        return selected

    def run_scrcpy_for_selected(self):
        """为选中的设备运行scrcpy命令"""
        selected_devices = self.get_selected_phones()
        if not selected_devices:
            messagebox.showwarning("警告", "请先选择手机！")
            return

        def run_scrcpy_thread():
            for device in selected_devices:
                try:
                    # 使用 -s 参数指定设备
                    subprocess.Popen(['scrcpy', '-s', device])
                    print(f"启动 scrcpy -s {device}")
                    time.sleep(0.5)  # 间隔0.5秒
                except FileNotFoundError:
                    messagebox.showerror("错误",
                                         f"未找到 'scrcpy' 命令，请确保scrcpy已安装并添加到系统PATH中。\n尝试启动设备: {device}")
                    break
                except Exception as e:
                    print(f"启动 scrcpy -s {device} 时出错: {e}")

        # 在后台线程中运行，避免阻塞UI
        thread = threading.Thread(target=run_scrcpy_thread)
        thread.start()

    def disconnect_selected(self):
        """断开选中的设备连接"""
        selected_devices = self.get_selected_phones()
        if not selected_devices:
            messagebox.showwarning("警告", "请先选择手机！")
            return

        disconnected_count = 0
        failed_disconnections = []

        for device in selected_devices:
            # 检查设备ID是否是IP:端口格式
            if self.is_valid_ip_port(device):
                success, message = self.run_adb_disconnect(device)
                if success:
                    disconnected_count += 1
                    print(f"断开连接成功: {device}")
                else:
                    failed_disconnections.append((device, message))
                    print(f"断开连接失败: {device}, 原因: {message}")
            else:
                # 如果不是IP:端口格式，可能是本地设备，直接从列表中移除可能不够，仍需尝试disconnect
                # ADB disconnect 通常用于网络连接的设备，对于USB设备一般不使用disconnect命令，而是物理拔掉。
                # 这里我们仍然尝试执行disconnect，看是否有预期效果。
                # 为了保持一致性，也尝试使用设备ID执行disconnect
                success, message = self.run_adb_disconnect(device)
                if success:
                    disconnected_count += 1
                    print(f"断开连接成功: {device}")
                else:
                    # 对于非网络连接的设备，disconnect可能会失败，这是正常的
                    # 可以选择记录或忽略
                    failed_disconnections.append((device, message))
                    print(f"断开连接失败 (可能为本地设备): {device}, 原因: {message}")

        # 显示结果
        result_message = f"尝试断开 {len(selected_devices)} 个设备的连接。\n成功断开: {disconnected_count} 个。"
        if failed_disconnections:
            failed_list = "\n".join([f"{dev}: {msg}" for dev, msg in failed_disconnections])
            result_message += f"\n\n以下设备断开失败:\n{failed_list}"

        messagebox.showinfo("断开连接结果", result_message)

        # 刷新手机列表页面以反映最新的连接状态
        self.show_phones()


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()



