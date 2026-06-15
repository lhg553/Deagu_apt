"""
대구 아파트 부동산 수집기 — GUI 진입점

tkinter 기반. main.run(args) 를 백그라운드 스레드에서 실행하고
실시간 로그를 화면에 출력합니다.
"""
import os
import sys
import queue
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ── 경로 설정 ─────────────────────────────────────────────────────
# PyInstaller EXE: sys.executable 디렉터리
# 일반 스크립트: 스크립트 디렉터리
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)  # .env·출력파일 위치 고정

# PyInstaller EXE 실행 시 Playwright가 번들 내부가 아닌
# 시스템 설치 경로(%LOCALAPPDATA%\ms-playwright)에서 브라우저를 찾도록 설정
if getattr(sys, 'frozen', False):
    _pw_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright')
    if os.path.isdir(_pw_path):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = _pw_path


# ── stdout 리디렉션 (스레드 → 큐) ─────────────────────────────────
# 여러 구를 동시 수집할 때 각 스레드의 출력을 [구명] 접두사로 구분.
# print()가 조각으로 들어오므로 스레드별 버퍼에 모아 줄 단위로 큐에 넣는다.

_tls = threading.local()


class _LogWriter:
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, s: str):
        if not s:
            return
        buf = getattr(_tls, 'buf', '') + s
        tag = getattr(_tls, 'tag', '')
        while '\n' in buf:
            line, buf = buf.split('\n', 1)
            self._q.put(('msg', (f'[{tag}] ' if tag else '') + line + '\n'))
        _tls.buf = buf

    def flush(self):
        pass


# ── 메인 앱 ──────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('대구 아파트 부동산 수집기')
        self.geometry('1000x680')
        self.minsize(820, 560)

        # Windows 비주얼 스타일
        style = ttk.Style(self)
        try:
            style.theme_use('vista')
        except Exception:
            pass

        self._q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._last_output = ''
        self._stop_event = threading.Event()

        # tkinter 변수
        # 구별 체크박스 (다중 선택). 기본값: 수성구만 선택
        self.DISTRICTS = ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군']
        self._district_vars = {gu: tk.BooleanVar(value=(gu == '수성구'))
                               for gu in self.DISTRICTS}
        self._source_var   = tk.StringVar(value='both')
        self._months_var   = tk.IntVar(value=12)
        self._output_var   = tk.StringVar()
        self._test_var     = tk.BooleanVar(value=False)
        self._kakao_var    = tk.StringVar()
        self._molit_var    = tk.StringVar()

        # .env에서 키 초기화
        kakao, molit = self._read_env_keys()
        self._kakao_var.set(kakao)
        self._molit_var.set(molit)

        self._build_ui()
        self._poll()

    # ── .env 읽기/쓰기 ───────────────────────────────────────────

    @staticmethod
    def _env_file() -> str:
        return os.path.join(BASE_DIR, '.env')

    def _read_env_keys(self) -> tuple[str, str]:
        kakao = molit = ''
        p = self._env_file()
        if os.path.isfile(p):
            for line in open(p, encoding='utf-8'):
                line = line.strip()
                if line.startswith('KAKAO_API_KEY='):
                    kakao = line.split('=', 1)[1].strip().strip('"\'')
                elif line.startswith('MOLIT_API_KEY='):
                    molit = line.split('=', 1)[1].strip().strip('"\'')
        return kakao, molit

    def _write_env_key(self, key: str, val: str):
        p = self._env_file()
        lines = open(p, encoding='utf-8').readlines() if os.path.isfile(p) else []
        done = False
        for i, line in enumerate(lines):
            if line.strip().startswith(key + '='):
                lines[i] = f'{key}={val}\n'
                done = True
        if not done:
            lines.append(f'{key}={val}\n')
        with open(p, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        self._log(f'[저장] {key} → .env\n', 'ok')

    # ── UI 구성 ──────────────────────────────────────────────────

    def _build_ui(self):
        self.configure(bg='#f0f2f5')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # 헤더
        hdr = tk.Frame(self, bg='#1F497D', pady=14)
        hdr.grid(row=0, column=0, sticky='ew')
        tk.Label(hdr, text='대구 아파트 부동산 수집기',
                 bg='#1F497D', fg='white',
                 font=('Malgun Gothic', 16, 'bold')).pack()
        tk.Label(hdr, text='네이버 부동산 호가  ·  국토교통부 실거래가  →  Excel',
                 bg='#1F497D', fg='#b0cce8',
                 font=('Malgun Gothic', 9)).pack()

        # 본문
        body = tk.Frame(self, bg='#f0f2f5', padx=10, pady=8)
        body.grid(row=1, column=0, sticky='nsew')
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_settings(body)
        self._build_logpanel(body)

        # 상태바
        self._status_var = tk.StringVar(value='준비')
        tk.Label(self, textvariable=self._status_var,
                 bg='#d0d4d8', relief='sunken', anchor='w', padx=8,
                 font=('Malgun Gothic', 9)).grid(row=2, column=0, sticky='ew')

    def _build_settings(self, parent):
        frm = ttk.LabelFrame(parent, text=' 수집 설정 ', padding=12)
        frm.grid(row=0, column=0, sticky='ns', padx=(0, 8))

        r = 0

        # ── 지역 (다중 선택) ──────────────────────────────────────
        hdr_f = tk.Frame(frm)
        hdr_f.grid(row=r, column=0, columnspan=3, sticky='ew', pady=(0, 3))
        tk.Label(hdr_f, text='수집 지역 (다중 선택)',
                 font=('Malgun Gothic', 9, 'bold')).pack(side='left')
        ttk.Button(hdr_f, text='전체 선택', width=8,
                   command=self._select_all_districts).pack(side='right')
        ttk.Button(hdr_f, text='전체 해제', width=8,
                   command=self._clear_all_districts).pack(side='right', padx=(0, 4))
        r += 1

        # 8개 구를 3열 그리드 체크박스로 배치
        for idx, gu in enumerate(self.DISTRICTS):
            dr, dc = divmod(idx, 3)
            ttk.Checkbutton(frm, text=gu, variable=self._district_vars[gu]).grid(
                row=r + dr, column=dc, sticky='w')
        r += (len(self.DISTRICTS) + 2) // 3  # 사용한 행 수

        ttk.Separator(frm).grid(row=r, column=0, columnspan=3, sticky='ew', pady=5)
        r += 1

        # ── 데이터 소스 ───────────────────────────────────────────
        tk.Label(frm, text='데이터 소스', font=('Malgun Gothic', 9, 'bold')).grid(
            row=r, column=0, columnspan=3, sticky='w', pady=(0, 3))
        r += 1
        for col, (val, label) in enumerate([
            ('both', '호가+실거래'), ('naver', '호가만'), ('molit', '실거래만')
        ]):
            ttk.Radiobutton(frm, text=label, variable=self._source_var,
                            value=val, command=self._update_months_state
                            ).grid(row=r, column=col, sticky='w')
        r += 1

        # 실거래 기간
        mf = tk.Frame(frm)
        mf.grid(row=r, column=0, columnspan=3, sticky='w', pady=(4, 0))
        tk.Label(mf, text='실거래 기간  ').pack(side='left')
        self._months_spin = ttk.Spinbox(mf, from_=1, to=24, width=4,
                                        textvariable=self._months_var)
        self._months_spin.pack(side='left')
        tk.Label(mf, text='  개월').pack(side='left')
        r += 1

        ttk.Separator(frm).grid(row=r, column=0, columnspan=3, sticky='ew', pady=5)
        r += 1

        # ── API 키 ────────────────────────────────────────────────
        tk.Label(frm, text='API 키  (입력 후 [저장] → 다음 실행 시 자동 적용)',
                 font=('Malgun Gothic', 9, 'bold')).grid(
            row=r, column=0, columnspan=3, sticky='w')
        r += 1
        tk.Label(frm, text='카카오=위치정보(필수) · 국토부=실거래가(선택)',
                 font=('Malgun Gothic', 8), fg='#666').grid(
            row=r, column=0, columnspan=3, sticky='w', pady=(0, 3))
        r += 1
        for label, var, env_key in [
            ('카카오 API 키', self._kakao_var, 'KAKAO_API_KEY'),
            ('국토부 API 키', self._molit_var, 'MOLIT_API_KEY'),
        ]:
            tk.Label(frm, text=label, font=('Malgun Gothic', 9)).grid(
                row=r, column=0, columnspan=3, sticky='w')
            r += 1
            kf = tk.Frame(frm)
            kf.grid(row=r, column=0, columnspan=3, sticky='ew', pady=(0, 4))
            ent = ttk.Entry(kf, textvariable=var, show='*', width=26)
            ent.pack(side='left', fill='x', expand=True)
            ttk.Button(kf, text='👁', width=3,
                       command=lambda e=ent: e.configure(
                           show='' if e.cget('show') else '*'
                       )).pack(side='left', padx=2)
            ttk.Button(kf, text='저장', width=5,
                       command=lambda k=env_key, v=var: self._write_env_key(k, v.get())
                       ).pack(side='left')
            r += 1

        ttk.Separator(frm).grid(row=r, column=0, columnspan=3, sticky='ew', pady=5)
        r += 1

        # ── 저장 폴더 ─────────────────────────────────────────────
        tk.Label(frm, text='저장 폴더 (비우면 프로그램 폴더)', font=('Malgun Gothic', 9)).grid(
            row=r, column=0, columnspan=3, sticky='w')
        r += 1
        of = tk.Frame(frm)
        of.grid(row=r, column=0, columnspan=3, sticky='ew', pady=(0, 4))
        ttk.Entry(of, textvariable=self._output_var, width=26).pack(
            side='left', fill='x', expand=True)
        ttk.Button(of, text='찾기', width=5, command=self._browse_output).pack(
            side='left', padx=(2, 0))
        r += 1

        # ── 테스트 모드 ───────────────────────────────────────────
        ttk.Checkbutton(frm, text='테스트 모드 (단지 10개)',
                        variable=self._test_var).grid(
            row=r, column=0, columnspan=3, sticky='w', pady=(2, 0))
        r += 1

        ttk.Separator(frm).grid(row=r, column=0, columnspan=3, sticky='ew', pady=8)
        r += 1

        # ── 버튼 ──────────────────────────────────────────────────
        bf = tk.Frame(frm)
        bf.grid(row=r, column=0, columnspan=3)
        self._start_btn = ttk.Button(bf, text='▶  수집 시작', width=15,
                                     command=self._start)
        self._start_btn.pack(side='left', padx=4)
        self._stop_btn = ttk.Button(bf, text='■  중지', width=9,
                                    command=self._stop, state='disabled')
        self._stop_btn.pack(side='left', padx=4)
        self._open_btn = ttk.Button(bf, text='파일 열기', width=11,
                                    command=self._open_result, state='disabled')
        self._open_btn.pack(side='left', padx=4)
        ttk.Button(bf, text='❓ 사용법', width=9,
                   command=self._show_help).pack(side='left', padx=4)

    def _build_logpanel(self, parent):
        frm = ttk.LabelFrame(parent, text=' 수집 로그 ', padding=8)
        frm.grid(row=0, column=1, sticky='nsew')
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)

        self._progress = ttk.Progressbar(frm, mode='indeterminate')
        self._progress.grid(row=0, column=0, sticky='ew', pady=(0, 5))

        self._log_text = scrolledtext.ScrolledText(
            frm, state='disabled', wrap='word',
            font=('Consolas', 9),
            bg='#1e1e1e', fg='#d4d4d4',
            insertbackground='white', relief='flat', bd=0)
        self._log_text.grid(row=1, column=0, sticky='nsew')

        for tag, color in [
            ('ok',     '#4ec9b0'),
            ('info',   '#9cdcfe'),
            ('warn',   '#f0c05a'),
            ('err',    '#f44747'),
            ('normal', '#d4d4d4'),
        ]:
            self._log_text.tag_config(tag, foreground=color)

        ttk.Button(frm, text='로그 지우기', command=self._clear_log).grid(
            row=2, column=0, sticky='e', pady=(4, 0))

    # ── 이벤트 핸들러 ─────────────────────────────────────────────

    def _update_months_state(self):
        s = 'disabled' if self._source_var.get() == 'naver' else 'normal'
        self._months_spin.configure(state=s)

    def _select_all_districts(self):
        for v in self._district_vars.values():
            v.set(True)

    def _clear_all_districts(self):
        for v in self._district_vars.values():
            v.set(False)

    def _selected_districts(self) -> list:
        return [gu for gu in self.DISTRICTS if self._district_vars[gu].get()]

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=BASE_DIR, title='저장 폴더 선택')
        if path:
            self._output_var.set(path)

    def _show_help(self):
        msg = (
            '【 사용 순서 】\n'
            '1) API 키 입력 후 [저장]\n'
            '    · 카카오 키 = 지하철·학교·마트 위치정보 (필수)\n'
            '    · 국토부 키 = 실거래가 (선택, 없으면 호가만)\n'
            '2) 수집할 구를 체크 (여러 개 가능, [전체 선택] 버튼)\n'
            '3) [▶ 수집 시작]\n\n'
            '【 동시 수집 】\n'
            '구를 여러 개 고르면 2개씩 동시에 수집해 시간을 줄입니다.\n\n'
            '【 결과 파일 】\n'
            '· {구}_부동산_날짜.xlsx — 구별 개별 파일\n'
            '· 대구통합_부동산_날짜.xlsx — 2개 이상 선택 시 합친 통합본\n'
            '· 시트: 호가_단지요약 / 매물상세 / 실거래가\n'
            '  (현재 매물 없는 단지도 단지 정보는 포함)\n\n'
            '【 예상 시간 】\n'
            '작은 구 4~6분, 큰 구 15~20분, 전체 8구 약 40분\n\n'
            '자세한 내용은 프로그램 폴더의 "사용설명서.txt" 참고'
        )
        messagebox.showinfo('사용법', msg)

    def _stop(self):
        self._stop_event.set()
        self._stop_btn.configure(state='disabled')
        self._status_var.set('중지 요청 중... (현재 구 완료 후 종료)')

    def _clear_log(self):
        self._log_text.configure(state='normal')
        self._log_text.delete('1.0', 'end')
        self._log_text.configure(state='disabled')

    def _open_result(self):
        if self._last_output and os.path.isfile(self._last_output):
            os.startfile(self._last_output)
        else:
            messagebox.showinfo('파일 없음', '저장된 파일을 찾을 수 없습니다.')

    # ── 수집 실행 ─────────────────────────────────────────────────

    def _start(self):
        if self._worker and self._worker.is_alive():
            messagebox.showwarning('진행 중', '수집이 이미 진행 중입니다.')
            return

        districts = self._selected_districts()
        if not districts:
            messagebox.showwarning('지역 미선택', '수집할 구를 1개 이상 선택하세요.')
            return

        out_dir = self._output_var.get().strip() or BASE_DIR
        if not os.path.isdir(out_dir):
            messagebox.showwarning('폴더 없음', f'저장 폴더가 없습니다:\n{out_dir}')
            return

        config = {
            'districts': districts,
            'source':    self._source_var.get(),
            'months':    self._months_var.get(),
            'molit_key': self._molit_var.get().strip(),
            'kakao_key': self._kakao_var.get().strip(),
            'out_dir':   out_dir,
            'test':      self._test_var.get(),
        }

        self._stop_event.clear()
        self._start_btn.configure(state='disabled', text='⏳  수집 중...')
        self._stop_btn.configure(state='normal')
        self._open_btn.configure(state='disabled')
        self._progress.start(12)
        self._status_var.set('수집 중...')
        self._log(
            f'\n{"─" * 52}\n'
            f'수집 시작: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'지역: {", ".join(districts)} ({len(districts)}개)  |  소스: {config["source"]}'
            f'  |  기간: {config["months"]}개월\n'
            f'{"─" * 52}\n',
            'info'
        )

        self._worker = threading.Thread(
            target=self._worker_fn, args=(config,), daemon=True)
        self._worker.start()

    def _worker_fn(self, config: dict):
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _LogWriter(self._q)
        try:
            if config['kakao_key']:
                os.environ['KAKAO_API_KEY'] = config['kakao_key']
            if config['molit_key']:
                os.environ['MOLIT_API_KEY'] = config['molit_key']

            from argparse import Namespace
            from concurrent.futures import ThreadPoolExecutor
            import main as _main

            districts = config['districts']
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            multi = len(districts) > 1
            done_files = []
            done_lock = threading.Lock()
            stop_event = self._stop_event

            def _run_one(gu):
                if stop_event.is_set():
                    return
                # 스레드별 로그 접두사 (구 2개 이상 동시 실행 시 구분)
                _tls.tag = gu if multi else ''
                _tls.buf = ''
                out = os.path.join(config['out_dir'], f'{gu}_부동산_{ts}.xlsx')
                print(f'========== {gu} 수집 시작 ==========')
                ns = Namespace(
                    district=gu, source=config['source'], months=config['months'],
                    molit_key=config['molit_key'], kakao_key=config['kakao_key'],
                    output=out, test=config['test'],
                )
                try:
                    _main.run(ns)
                    if os.path.isfile(out):
                        with done_lock:
                            done_files.append((gu, out))
                except SystemExit as e:
                    if e.code not in (None, 0):
                        print(f'[경고] {gu} 수집 중단(코드 {e.code})')
                    elif os.path.isfile(out):
                        with done_lock:
                            done_files.append((gu, out))
                except Exception:
                    import traceback
                    print(f'[오류] {gu} 수집 실패:\n{traceback.format_exc()}')

            # ── 2개 구 동시 실행 (개별 파일로 저장) ────────────────
            with ThreadPoolExecutor(max_workers=2) as ex:
                list(ex.map(_run_one, districts))

            _tls.tag = ''  # 이후 로그는 접두사 없이
            if stop_event.is_set():
                self._q.put(('stopped', None))
                return
            if not done_files:
                self._q.put(('err', '수집된 파일이 없습니다.\n'))
                return

            # 선택 순서대로 정렬
            order = {gu: i for i, gu in enumerate(districts)}
            done_files.sort(key=lambda x: order.get(x[0], 999))
            paths = [p for _, p in done_files]
            final = paths[-1]

            # ── 통합 파일 생성 (구 2개 이상일 때) ─────────────────
            if len(paths) >= 2:
                print(f'\n========== 통합 파일 생성 ({len(paths)}개 구) ==========')
                from combine import combine_files
                merged = os.path.join(config['out_dir'], f'대구통합_부동산_{ts}.xlsx')
                try:
                    result = combine_files(paths, merged)
                    if result:
                        final = result
                except Exception:
                    import traceback
                    print(f'[오류] 통합 실패:\n{traceback.format_exc()}')

            self._q.put(('done', final))
        except Exception:
            import traceback
            self._q.put(('err', traceback.format_exc()))
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

    # ── 큐 폴링 (100ms) ──────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                kind, content = self._q.get_nowait()
                if kind == 'msg':
                    self._log(content)
                elif kind == 'done':
                    self._on_done(content)
                elif kind == 'stopped':
                    self._log('수집이 중지되었습니다.\n', 'warn')
                    self._on_stopped()
                elif kind == 'err':
                    self._log(content, 'err')
                    self._on_stopped()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, msg: str, tag: str = ''):
        if not msg:
            return
        if not tag:
            lower = msg.lower()
            if '[warning]' in lower or '경고' in lower:
                tag = 'warn'
            elif any(x in lower for x in ('완료', '저장', '===', '---', '수집')):
                tag = 'info'
            else:
                tag = 'normal'
        self._log_text.configure(state='normal')
        self._log_text.insert('end', msg, tag)
        self._log_text.see('end')
        self._log_text.configure(state='disabled')

    def _on_done(self, output: str):
        self._last_output = os.path.abspath(output)
        self._on_stopped()
        self._open_btn.configure(state='normal')
        self._status_var.set(f'완료  →  {os.path.basename(output)}')
        self._log(f'\n✓ 저장 완료: {self._last_output}\n', 'ok')

    def _on_stopped(self):
        self._progress.stop()
        self._start_btn.configure(state='normal', text='▶  수집 시작')
        self._stop_btn.configure(state='disabled')
        if self._status_var.get() in ('수집 중...', '중지 요청 중... (현재 구 완료 후 종료)'):
            self._status_var.set('중지됨' if self._stop_event.is_set() else '준비')


# ── 진입점 ────────────────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
