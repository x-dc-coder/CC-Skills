#!/usr/bin/env python3
'''gpu_safe_subprocess 回归测试：HEADLESS 强制规则 + 现有能力。</br>用法: python3 test_headless.py</br>'''
import sys, os, warnings
sys.path.insert(0, '/home/dc/.dsh/skills/wsl-windows-bridge/scripts')
import gpu_safe_subprocess as g

PASS = 0; FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond: PASS += 1; print(f'  [PASS] {name}'); 
    else: FAIL += 1; print(f'  [FAIL] {name} {detail}')

PYEXE = r'E:\\venvs\\mpca\\Scripts\\pythonw.exe'  # 本项目无窗解释器
PYEXE_PY = r'E:\\venvs\\mpca\\Scripts\\python.exe'

print('== R1. _ensure_pythonw 强制规则 ==')
# R1.1 裸名拒绝
try:
    g._ensure_pythonw('python.exe'); check('R1.1 裸名被拒', False)
except ValueError: check('R1.1 裸名被拒', True)
# R1.2 pythonw 直接通过
check('R1.2 pythonw 通过', g._ensure_pythonw(PYEXE) == PYEXE)
# R1.3 python.exe 自动替换为 pythonw（同目录存在时）
with warnings.catch_warnings(record=True) as w:
    r3 = g._ensure_pythonw(PYEXE_PY)
check('R1.3 python.exe→pythonw 替换', r3.lower().endswith('pythonw.exe'), r3)
check('R1.4 替换触发警告', any('HEADLESS' in str(x.message) for x in w))
# R1.5 不存在解释器 strict 报错
try:
    g._ensure_pythonw(r'E:\\nope\\Scripts\\python.exe'); check('R1.5 无pythonw strict报错', False)
except ValueError: check('R1.5 无pythonw strict报错', True)
try:
    g._ensure_pythonw(r'E:\\nope\\Scripts\\anything.exe'); check('R1.6 未知名 strict报错', False)
except ValueError: check('R1.6 未知名 strict报错', True)

print('== R2. run_gpu_windows HEADLESS 直调（不经 cmd.exe） ==')
# R2.1 pythonw 无弹窗执行
r = g.run_gpu_windows(PYEXE, 'import sys; print(sys.executable.split(chr(92))[-1]); print("HELLO_HEADLESS")', timeout=60)
check('R2.1 退出码0', r.returncode == 0, r.returncode)
check('R2.2 输出含 HELLO_HEADLESS', 'HELLO_HEADLESS' in (r.stdout or ''))
check('R2.3 用的是 pythonw（无窗）', 'pythonw.exe' in (r.stdout or ''), r.stdout)
# R2.2 传 python.exe 自动改 pythonw 仍成功
r2 = g.run_gpu_windows(PYEXE_PY, 'print("VIA_AUTO_PYTHONW")', timeout=60)
check('R2.4 python.exe 自动改 pythonw 仍执行成功', r2.returncode == 0 and 'VIA_AUTO_PYTHONW' in (r2.stdout or ''))

print('== R3. launch_detached 回归（后台+日志+PID） ==')
h = g.launch_detached(
    py_exe=PYEXE,
    code='import os,time; print("DETACH_PID", os.getpid(), flush=True); time.sleep(2); print("DETACH_DONE", flush=True)',
    job_name='reg_test',
)
check('R3.1 返回 handle', hasattr(h, 'win_pid'))
check('R3.2 PID 文件存在', os.path.exists(h.wsl_pid_path))
import time as _t; _t.sleep(4)
log = open(h.wsl_log_path, encoding='utf-8').read() if os.path.exists(h.wsl_log_path) else ''
check('R3.3 日志含 DETACH_DONE', 'DETACH_DONE' in log, log[-100:])
check('R3.4 日志含 stdio 绑定(PID 可见)', 'DETACH_PID' in log)

print('== R4. _headless_cmd 命令构成 ==')
c = g._headless_cmd(PYEXE, 'print(1)')
check('R4.1 无 cmd.exe 中转', 'cmd.exe' not in c and '/c' not in c)
check('R4.2 含 -u -X utf8 防护', '-u' in c and '-X' in c and 'utf8' in c)
check('R4.3 路径转 /mnt/e', c[0].startswith('/mnt/'), c[0])

print(f'\n==== 回归结果: {PASS} PASS / {FAIL} FAIL ====')
sys.exit(1 if FAIL else 0)