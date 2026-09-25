import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, CornerDownLeft, Loader2 } from 'lucide-react';
import { navPageIndex } from '../../config/nav';
import { listTrips } from '../../api/planner';
import { listPolicyDocs } from '../../api/organization';
import { listGuides } from '../../api/guides';

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 平台相关的快捷键提示 */
const IS_MAC =
  typeof navigator !== 'undefined' && /mac/i.test(navigator.platform || navigator.userAgent || '');
export const COMMAND_HINT = IS_MAC ? '⌘K' : 'Ctrl K';

/** 每个来源最多渲染多少条，避免一次刷满屏 */
const MAX_PER_SOURCE = 6;

interface Command {
  key: string;
  label: string;
  sub?: string;
  to: string;
  group: string;
  icon?: any;
  hay?: string;
  idx?: number;
}

/**
 * 命令面板（⌘K / Ctrl+K）
 *
 * 存在的意义：侧边栏只放高频入口，低频入口（系统管理 / 某条具体行程 / 某篇语料…）
 * 用「想不起来在哪就问一下」的方式承载 —— 这是 Linear / Vercel / Stripe 的通用做法。
 *
 * 静态来源：nav.js 的页面登记表（即时可用）。
 * 动态来源：行程 / 知识语料，打开时并行拉取；任一来源失败都静默降级，
 *          面板本身绝不能因为某个接口挂了就打不开。
 */

async function loadTripCommands(): Promise<Command[]> {
  const d: any = await listTrips();
  return (d?.trips || []).map((t: any) => ({
    key: `trip:${t.trip_id}`,
    label: t.title || '未命名行程',
    sub:
      [t.destination, [t.start_date, t.end_date].filter(Boolean).join(' ~ ')]
        .filter(Boolean)
        .join(' · ') || '未填写日期',
    to: `/trips/${t.trip_id}`,
    group: '行程',
  }));
}

async function loadCorpusCommands(): Promise<Command[]> {
  const [p, g] = await Promise.all([listPolicyDocs(), listGuides()]);
  const map = (arr: any[], prefix: string) =>
    (arr || []).map((d: any, i: number) => ({
      key: `${prefix}:${d.doc_id || d.guide_id || i}`,
      label: d.title,
      sub: [d.category, d.source].filter(Boolean).join(' · '),
      to: '/corpus',
      group: '知识语料',
    }));
  return [...map(p?.documents, 'doc'), ...map(g?.documents, 'guide')];
}

export const CommandPalette = ({ open, onOpenChange }: CommandPaletteProps) => {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [remote, setRemote] = useState<Command[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  // 全局快捷键：面板关闭时也能唤起
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);

  // 打开时重置并并行拉取动态结果
  useEffect(() => {
    if (!open) return;
    setQ('');
    setActive(0);
    setLoading(true);
    let alive = true;
    const tasks = [loadTripCommands(), loadCorpusCommands()];
    Promise.allSettled(tasks).then((rs) => {
      if (!alive) return;
      setRemote(rs.flatMap((r) => (r.status === 'fulfilled' ? r.value : [])));
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [open]);

  const pages = useMemo<Command[]>(
    () =>
      navPageIndex().map((p: any) => ({
        key: `page:${p.to}`,
        label: p.label,
        sub: p.desc,
        to: p.to,
        group: '页面',
        icon: p.icon,
        hay: `${p.label} ${p.desc || ''} ${p.keywords || ''} ${p.group}`.toLowerCase(),
      })),
    [],
  );

  const groups = useMemo(() => {
    const query = q.trim().toLowerCase();
    const all = [...pages, ...remote];
    const matched = query
      ? all.filter((c) => `${c.label} ${c.sub || ''} ${c.hay || ''}`.toLowerCase().includes(query))
      : all;

    const order: string[] = [];
    const bucket: Record<string, Command[]> = {};
    matched.forEach((c) => {
      if (!bucket[c.group]) {
        bucket[c.group] = [];
        order.push(c.group);
      }
      if (bucket[c.group].length < MAX_PER_SOURCE) bucket[c.group].push(c);
    });

    let n = 0;
    return order.map((g) => ({ label: g, items: bucket[g].map((c) => ({ ...c, idx: n++ })) }));
  }, [pages, remote, q]);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    setActive(0);
  }, [q]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  if (!open) return null;

  const go = (c?: Command) => {
    if (!c) return;
    onOpenChange(false);
    navigate(c.to);
  };

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      go(flat[active]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onOpenChange(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[12vh]"
      style={{ background: 'rgba(15, 23, 42, 0.45)' }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onOpenChange(false);
      }}
    >
      <div
        className="w-full max-w-[580px] rounded-2xl bg-white shadow-2xl overflow-hidden"
        style={{ border: '1px solid var(--line)' }}
      >
        <div className="flex items-center gap-2.5 px-4 h-12" style={{ borderBottom: '1px solid var(--line)' }}>
          <Search size={16} className="text-ink-400 shrink-0" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onInputKey}
            placeholder="搜索页面、行程、语料…"
            className="flex-1 min-w-0 text-sm outline-none placeholder:text-ink-400"
          />
          {loading && <Loader2 size={14} className="animate-spin text-ink-400 shrink-0" />}
          <kbd className="text-[10px] text-ink-400 border rounded px-1.5 py-0.5 shrink-0">Esc</kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-2">
          {flat.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-ink-400">
              {loading ? '正在检索…' : '没有匹配结果'}
            </div>
          )}
          {groups.map((g) => (
            <div key={g.label} className="px-2">
              <div className="px-2.5 pt-2 pb-1 text-[10px] tracking-[0.12em] uppercase text-ink-400">
                {g.label}
              </div>
              {g.items.map((c) => {
                const on = c.idx === active;
                return (
                  <button
                    key={c.key}
                    type="button"
                    data-idx={c.idx}
                    onMouseEnter={() => setActive(c.idx as number)}
                    onClick={() => go(c)}
                    className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-left cursor-pointer border-0 ${
                      on ? 'bg-primary-50' : 'bg-transparent'
                    }`}
                  >
                    {c.icon ? (
                      <c.icon size={15} className="shrink-0 text-ink-400" />
                    ) : (
                      <span className="w-[15px] shrink-0" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-ink-900 truncate">{c.label}</span>
                      {c.sub && <span className="block text-[11px] text-ink-400 truncate">{c.sub}</span>}
                    </span>
                    {on && <CornerDownLeft size={13} className="shrink-0 text-primary-500" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div
          className="flex items-center justify-between px-4 h-9 text-[11px] text-ink-400"
          style={{ borderTop: '1px solid var(--line)' }}
        >
          <span>↑↓ 选择 · ↵ 打开 · Esc 关闭</span>
          <span className="tnum">{flat.length} 个结果</span>
        </div>
      </div>
    </div>
  );
};
