import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Send, Bot, User, Sparkles, Plane, CalendarCheck, Map,
  FileText, ClipboardCheck, ChevronRight, MessageCircle, Loader2, RefreshCw, SquarePen,
  History,
} from 'lucide-react';
import { listModels, currentUserId } from '../api/auth';
import { listSessions } from '../api/journey';
import { chatStore, GREETING } from '../store/chatStore';
import { Badge, TripConfirmCard, Drawer, Button, EmptyState } from '../components';

const INTENT_LABELS = {
  plan: { label: '行程规划', tone: 'primary' },
  chat: { label: '行程问答', tone: 'blue' },
  manage: { label: '行程管理', tone: 'purple' },
  emergency: { label: '应急协助', tone: 'red' },
};

// v2 澄清选项（PRD §6.2）：缺场景时展示可点选项；日期等由用户文字补充
const CLARIFY_SCENE_OPTIONS = ['商务出差', '会议参展', '客户拜访', '团队出行', '个人出游'];
const CLARIFY_FALLBACK_LABEL = '你看着办，按常见差旅默认补全';

const SUGGESTIONS = [
  { icon: Plane, text: '9月15号广州飞北京出差，16号上午拜访国贸客户，17号下午返程' },
  { icon: CalendarCheck, text: '下周三部门5人去深圳参加三天行业展会，提前一天布展' },
  { icon: Map, text: '安排我到成都分公司做例行巡检，周二晚上团队聚餐' },
];

// 兜底模型列表：接口失败时用。注意 Hy-MT2 全系仅 8k 上下文且超限静默截断，
// 不适合做默认模型，故把上下文更长的放在前面。
const FALLBACK_MODELS = [
  { value: 'deepseek-v4-flash', label: 'DeepSeek V4' },
  { value: 'kimi-k3', label: 'Kimi K3' },
  { value: 'hy-mt2-pro', label: '混元 Pro' },
];

function ActionCard({ type, card, onOpen }) {
  const meta = {
    trip: { icon: Plane, tone: 'text-primary-600', bg: 'bg-primary-50 border-primary-100' },
    policy: { icon: FileText, tone: 'text-blue-600', bg: 'bg-blue-50 border-blue-100' },
    approval: { icon: ClipboardCheck, tone: 'text-amber-600', bg: 'bg-amber-50 border-amber-100' },
  }[type] || { icon: FileText, tone: 'text-ink-600', bg: 'bg-gray-50 border-gray-100' };
  const Icon = meta.icon;
  return (
    <button
      onClick={() => onOpen(type, card)}
      className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl border ${meta.bg} text-left hover:shadow-sm transition-shadow`}
    >
      <Icon size={15} className={`${meta.tone} shrink-0`} />
      <span className="flex-1 text-[13px] text-ink-700 truncate">
        {type === 'trip' ? '行程已生成，点击查看详情' : card.text}
      </span>
      <ChevronRight size={14} className="text-ink-400 shrink-0" />
    </button>
  );
}

export default function ChatPage() {
  const navigate = useNavigate();
  const [, setTick] = useState(0);
  const [hydrated, setHydrated] = useState(false);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('deepseek-v4-flash');
  const [modelOptions, setModelOptions] = useState(FALLBACK_MODELS);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  // 服务端活跃会话概览（诊断用）：确认当前登录身份的会话是否真的落到了后端
  const openSessions = async () => {
    setSessionsOpen(true);
    setSessionsLoading(true);
    try {
      const res = await listSessions();
      setSessions(res.sessions || []);
    } catch {
      setSessions([]);
    }
    setSessionsLoading(false);
  };

  const store = chatStore.get();
  const messages = store.messages || [GREETING];
  const loading = store.loading;

  // 水合一次：localStorage 快照 > 服务端会话历史 > 问候语（跨菜单/刷新不丢对话）
  useEffect(() => {
    let alive = true;
    chatStore.hydrate().then(() => {
      if (alive) setHydrated(true);
    });
    return () => { alive = false; };
  }, []);

  // 订阅 store（生成过程中消息在模块级持续更新）
  useEffect(() => chatStore.subscribe(() => setTick((x) => x + 1)), []);

  // 模型列表从后端配置拉取，失败时用内置兜底
  useEffect(() => {
    listModels()
      .then((res) => {
        const options = (res.models || []).map((m) => ({ value: m.model_id, label: m.label }));
        if (options.length) {
          setModelOptions(options);
          setModel(res.default_model || options[0].value);
        }
      })
      .catch(() => { /* 保留内置列表 */ });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  const sendText = (text) => {
    if (!text || loading) return;
    chatStore.send(text, model);
  };

  const send = () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    sendText(text);
  };

  const openCard = (type, card) => {
    if (type === 'trip' && card.id) navigate(`/trips/${card.id}`);
    else if (type === 'approval') navigate('/approval');
    else if (type === 'policy') navigate('/policy');
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const handleNewChat = () => {
    if (!confirm('开启新对话将清空当前聊天记录（已生成的行程与单据不受影响），确定继续？')) return;
    chatStore.reset();
  };

  // 空对话（仅问候语/刚开启新对话）时进入居中的「首页」视图
  const isEmptyChat = hydrated && messages.length <= 1 && !loading;

  return (
    <div className="h-full flex flex-col">
      {/* 顶部：非空对话时提供「新对话」入口 */}
      {hydrated && !isEmptyChat && (
        <div className="shrink-0 px-6 pt-3">
          <div className="max-w-3xl mx-auto flex justify-end gap-2">
            <button
              onClick={openSessions}
              title="查看服务端会话状态"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 transition-colors shadow-sm"
            >
              <History size={13} /> 会话
            </button>
            <button
              onClick={handleNewChat}
              disabled={loading}
              title="开启新对话"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 disabled:opacity-40 transition-colors shadow-sm"
            >
              <SquarePen size={13} /> 新对话
            </button>
          </div>
        </div>
      )}

      {/* Messages：空对话 → 居中的首页视图；有历史 → 气泡列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {!hydrated ? (
          <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={24} /></div>
        ) : isEmptyChat ? (
          <div className="min-h-full flex items-center justify-center px-6 py-8">
            <div className="w-full max-w-2xl">
              <div className="flex flex-col items-center text-center">
                <div className="w-14 h-14 rounded-2xl brand-mark text-white flex items-center justify-center shadow-lg shadow-primary-200 mb-4">
                  <Bot size={26} />
                </div>
                <h2 className="text-lg font-semibold text-ink-900 mb-1.5">企业行程智能助手</h2>
                <p className="text-[13px] text-ink-500 leading-relaxed max-w-lg">{GREETING.content}</p>
              </div>
              <div className="grid gap-2.5 mt-6">
                {SUGGESTIONS.map(({ icon: Icon, text }, idx) => (
                  <button
                    key={idx}
                    onClick={() => sendText(text)}
                    className="flex items-center gap-3 text-left px-4 py-3 rounded-xl bg-white border border-gray-200 text-sm text-ink-600 hover:border-primary-300 hover:text-primary-600 hover:shadow-sm transition-all"
                  >
                    <span className="w-8 h-8 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center shrink-0"><Icon size={15} /></span>
                    <span className="truncate">{text}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-5 px-6 py-6">
            {messages.map((msg, i) => {
              const isUser = msg.role === 'user';
              const lastAssistant = i === messages.length - 1 && msg.role === 'assistant';
              const intentCfg = INTENT_LABELS[msg.intent];
              const showCards = !isUser && (msg.cards?.length > 0 || (msg.followups?.length > 0 && !loading));
              return (
                <div key={i} className={`flex gap-3 ${isUser ? 'justify-end' : ''}`}>
                  {!isUser && (
                    <div className="w-9 h-9 rounded-xl brand-mark text-white flex items-center justify-center shrink-0 shadow-sm">
                      <Bot size={17} />
                    </div>
                  )}
                  <div className={`max-w-[78%] ${showCards ? 'flex-1 min-w-0' : ''}`}>
                    <div
                      className={`rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                        isUser
                          ? 'bg-gradient-to-br from-primary-600 to-primary-500 text-white rounded-br-md shadow-sm shadow-primary-200'
                          : 'card text-ink-900 rounded-bl-md'
                      }`}
                    >
                      {!isUser && (
                        <div className="flex items-center gap-2 mb-2">
                          {intentCfg ? (
                            <Badge tone={intentCfg.tone}>{intentCfg.label}</Badge>
                          ) : (
                            <Badge tone="primary"><Sparkles size={11} />企业智行</Badge>
                          )}
                        </div>
                      )}
                      {msg.content || (
                        lastAssistant && loading ? (
                          <span className="flex items-center gap-1.5 py-1 text-[13px]">
                            {msg.progress ? (
                              <span className="flex items-center gap-2 text-ink-500">
                                <Loader2 size={13} className="animate-spin text-primary-500" />
                                <span>{msg.progress}</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5">
                                <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
                              </span>
                            )}
                          </span>
                        ) : null
                      )}
                    </div>

                    {/* 方案确认卡（S4）：草案未落库，确认后才提交审批 */}
                    {!isUser && !loading && msg.draft?.trip && (
                      <TripConfirmCard
                        trip={msg.draft.trip}
                        defaulted={msg.draft.defaulted}
                        busy={loading}
                        onConfirm={(trip) => chatStore.confirmDraft(trip)}
                        onEdit={() => {
                          const seed = chatStore.editDraft();
                          if (seed) {
                            setInput(seed);
                            inputRef.current?.focus();
                          }
                        }}
                        onCancel={() => chatStore.cancelDraft()}
                      />
                    )}

                    {/* 澄清选项 chips（S2）：缺场景时给可点选项 + 授权代填入口 */}
                    {!isUser && !loading && msg.clarify && (
                      <div className="mt-2">
                        <div className="flex flex-wrap gap-1.5">
                          {(msg.clarify.missing || []).includes('scene') &&
                            CLARIFY_SCENE_OPTIONS.map((s) => (
                              <button
                                key={s}
                                onClick={() => sendText(s)}
                                className="px-3 py-1.5 text-xs rounded-full bg-white border border-primary-200 text-primary-700 hover:bg-primary-50 transition-colors"
                              >
                                {s}
                              </button>
                            ))}
                        </div>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          <button
                            onClick={() => sendText('你看着办，按常见差旅默认补全')}
                            className="px-3 py-1.5 text-xs rounded-full bg-white border border-gray-200 text-ink-500 hover:border-primary-300 hover:text-primary-600 transition-colors"
                          >
                            {CLARIFY_FALLBACK_LABEL}
                          </button>
                        </div>
                        {(msg.clarify.missing || []).some((k) => k === 'start_date' || k === 'days') && (
                          <p className="mt-1.5 text-[11px] text-ink-400">
                            日期可直接回复，如「9/15 到 9/17」「下周一出发，3 天」
                          </p>
                        )}
                      </div>
                    )}

                    {/* 卡片式回答 */}
                    {!isUser && msg.cards?.length > 0 && (
                      <div className="mt-2 space-y-2">
                        {msg.cards.map((card, idx) => (
                          <ActionCard key={idx} type={card.type} card={card} onOpen={openCard} />
                        ))}
                      </div>
                    )}

                    {/* 补充追问 */}
                    {!isUser && !loading && msg.followups?.length > 0 && (
                      <div className="mt-2.5">
                        <p className="text-[11px] text-ink-400 mb-1.5 flex items-center gap-1">
                          <MessageCircle size={11} /> 继续问问：
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {msg.followups.map((q, idx) => (
                            <button
                              key={idx}
                              onClick={() => sendText(q)}
                              disabled={loading}
                              className="px-3 py-1.5 text-xs rounded-full bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 transition-colors disabled:opacity-50"
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  {isUser && (
                    <div className="w-9 h-9 rounded-xl bg-gray-100 border border-gray-200 text-ink-600 flex items-center justify-center shrink-0">
                      <User size={17} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 快捷建议：输入框上方常驻（有对话时）—— 每次回答后自动刷新为该意图固定 3 条；可「换一批」随机 */}
      {hydrated && !loading && !isEmptyChat && store.quick.length > 0 && (
        <div className="shrink-0 bg-white/70 px-6 pt-2.5 pb-1">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-medium text-ink-400 flex items-center gap-1">
                <MessageCircle size={11} /> {store.quickIntent && INTENT_LABELS[store.quickIntent] ? `${INTENT_LABELS[store.quickIntent].label} · 快捷建议` : '快捷建议'}
              </span>
              <button
                onClick={() => chatStore.quickRandom()}
                title="随机换一批建议"
                className="ml-auto flex items-center gap-1 text-[11px] text-ink-400 hover:text-primary-600 transition-colors"
              >
                <RefreshCw size={11} /> 换一批
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-1.5 pb-1.5">
              {store.quick.map((q) => (
                <button
                  key={q}
                  onClick={() => sendText(q)}
                  disabled={loading}
                  className="px-3 py-1.5 text-xs rounded-full bg-white border border-gray-200 text-ink-600 hover:border-primary-300 hover:text-primary-600 transition-colors disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="shrink-0 border-t border-gray-100 bg-white/80 backdrop-blur px-6 py-3.5">
        <div className="max-w-3xl mx-auto flex items-end gap-2 rounded-2xl border border-gray-200 bg-white p-2 shadow-sm focus-within:border-primary-300 focus-within:ring-2 focus-within:ring-primary-100 transition-all">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            title="选择模型"
            className="shrink-0 pl-2 pr-5 py-2 text-xs font-medium text-primary-600 bg-transparent border-r border-gray-100 cursor-pointer focus:outline-none"
          >
            {modelOptions.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="描述你的差旅需求，例如：下周三去深圳参加三天展会..."
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm py-2 focus:outline-none placeholder:text-ink-400 max-h-32"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="w-9 h-9 rounded-xl bg-primary-600 text-white flex items-center justify-center disabled:opacity-40 hover:bg-primary-700 transition-colors shrink-0"
          >
            <Send size={16} />
          </button>
        </div>
        <p className="text-center text-[11px] text-ink-400 mt-2">Enter 发送 · Shift+Enter 换行 · 回答下方可点击卡片与追问 · 切换菜单对话不丢失 · 右上角「新对话」重新开始</p>
      </div>

      <Drawer
        open={sessionsOpen}
        title="会话状态"
        subtitle="服务端内存中的活跃会话，用于确认身份与会话是否真的落到后端"
        onClose={() => setSessionsOpen(false)}
      >
        <div className="space-y-4">
          <div className="rounded-xl border border-primary-100 bg-primary-50/60 px-4 py-3 text-[12px] text-ink-600 leading-relaxed">
            当前身份：<span className="font-medium text-ink-900">{currentUserId() || '未登录'}</span>。
            会话 ID 取自登录用户名，换账号登录会进入不同会话，上下文互不串。
          </div>

          {sessionsLoading ? (
            <div className="flex justify-center py-10">
              <Loader2 className="animate-spin text-ink-400" size={20} />
            </div>
          ) : sessions.length === 0 ? (
            <EmptyState
              icon={<History size={20} />}
              title="暂无活跃会话"
              description="后端进程重启后会话为空，发一条消息即可建立"
            />
          ) : (
            <div className="space-y-2">
              {sessions.map((s) => {
                const isCurrent = s.session_id === currentUserId();
                return (
                  <div
                    key={s.session_id}
                    className={`rounded-xl border px-3.5 py-3 ${
                      isCurrent ? 'border-primary-200 bg-primary-50/50' : 'border-gray-100 bg-gray-50/60'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[13px] font-medium text-ink-900 font-mono truncate">{s.session_id}</span>
                      {isCurrent && <Badge tone="primary">当前会话</Badge>}
                      <span className="ml-auto text-[11px] text-ink-400 tnum shrink-0">{s.message_count} 条消息</span>
                    </div>
                    {s.last_message && (
                      <p className="text-[12px] text-ink-400 truncate">{s.last_message}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="pt-3 border-t border-gray-100">
            <Button type="secondary" size="sm" block onClick={openSessions}>
              <RefreshCw size={13} className="mr-1.5" /> 刷新列表
            </Button>
          </div>
        </div>
      </Drawer>
    </div>
  );
}
