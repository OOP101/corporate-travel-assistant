import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapPin, Calendar, Trash2, Plus, Plane, Loader2, ArrowRight } from 'lucide-react';
import { listTrips, deleteTrip, generateTripStream } from '../api/planner';
import { generationStore } from '../store/generationStore';
import { PageHeader, ModalForm, Button, Badge, EmptyState } from '../components';

const GRADIENTS = [
  'from-primary-500 to-purple-500',
  'from-blue-500 to-cyan-400',
  'from-amber-500 to-orange-400',
  'from-emerald-500 to-teal-400',
  'from-pink-500 to-rose-400',
];

// 把生成完成的行程数据格式化为可读摘要（避免把原始 JSON 刷上屏）
function formatTripBrief(trip) {
  const lines = [];
  if (trip.title) lines.push(`🧳 标题：${trip.title}`);
  if (trip.destination) lines.push(`📍 目的地：${trip.destination}`);
  const dates = [trip.start_date, trip.end_date].filter(Boolean).join(' → ');
  if (dates) lines.push(`📅 日期：${dates}`);
  if (trip.budget_total) lines.push(`💰 预算：¥${Number(trip.budget_total).toLocaleString()}`);
  (trip.days || []).forEach((d, i) => {
    const date = d.date || '';
    const theme = d.theme || '';
    const label = [date, theme].filter(Boolean).join(' · ');
    lines.push(`  Day ${i + 1}${label ? ` ${label}` : ''}（${(d.activities || []).length} 项活动）`);
  });
  if (Array.isArray(trip.checklist) && trip.checklist.length) {
    lines.push(`✅ 出行清单：${trip.checklist.length} 项`);
  }
  if (!lines.length) lines.push('行程已生成');
  return lines.join('\n');
}

export default function TripsPage() {
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showGenerate, setShowGenerate] = useState(false);
  const [gen, setGen] = useState(() => generationStore.get());
  const navigate = useNavigate();
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // 订阅全局生成状态：跨菜单切换不丢失流式进度与结果
  useEffect(() => generationStore.subscribe(setGen), []);

  const loadTrips = async () => {
    setLoading(true);
    try {
      const data = await listTrips('web-user');
      setTrips(data.trips || []);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { loadTrips(); }, []);

  const handleDelete = async (tripId) => {
    if (!confirm('确定删除该行程？')) return;
    await deleteTrip(tripId);
    loadTrips();
  };

  const handleGenerate = (values) => {
    const query = values.query?.trim();
    if (!query) return;
    setShowGenerate(false);

    // 重置并写入初始状态（模块级 store，切菜单不丢）
    generationStore.reset();
    generationStore.set({ status: 'analyzing', query });

    let rawLen = 0;
    const approvalNote = [];

    generateTripStream(query, {}, (evt) => {
      if (evt.event === 'status') {
        generationStore.set({ status: 'analyzing', statusText: evt.content });
      } else if (evt.event === 'chunk') {
        // 不透传原始行程 JSON；只把真实到达节奏折算成进度
        rawLen += (evt.content || '').length;
        generationStore.set({
          status: 'generating',
          statusText: `行程内容生成中…已接收 ${rawLen} 字`,
        });
      } else if (evt.event === 'policy') {
        if (evt.has_violations) approvalNote.push(`⚠️ 政策检查：${evt.content || '存在需关注项'}`);
        else approvalNote.push(`✅ 政策检查：${evt.content || '通过'}`);
      } else if (evt.event === 'approval') {
        approvalNote.push(`🖊️ ${evt.content || '已发起审批'}`);
      } else if (evt.event === 'done') {
        // 完成：展示格式化摘要（而不是堆满原始 JSON）
        const brief = evt.trip ? formatTripBrief(evt.trip) : '行程已生成 ✓';
        const tail = approvalNote.length ? '\n' + approvalNote.join('\n') : '';
        generationStore.set({
          status: 'done',
          text: brief + tail,
          tripId: evt.trip_id || null,
          trip: evt.trip || null,
        });
        // 挂载中直接跳详情；切走则在返回时由 loadTrips 在列表展示
        if (mountedRef.current) {
          if (evt.trip_id) navigate(`/trips/${evt.trip_id}`);
          else loadTrips();
        } else {
          loadTrips();
        }
      } else if (evt.event === 'error') {
        generationStore.set({ status: 'error', error: evt.content });
      }
    });
    // 注意：不在此 abort —— 允许切菜单后后台继续生成，返回时续显
  };

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="差旅行程"
        subtitle="一句话生成可执行的差旅计划，随时查看与复用"
        actions={
          <Button onClick={() => setShowGenerate(true)}>
            <Plus size={15} /> 新建行程
          </Button>
        }
      />

      {gen.status && gen.status !== 'idle' && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-primary-50 border border-primary-100 text-primary-800 text-sm">
          <div className="flex items-center gap-2 mb-1.5 font-medium">
            <Loader2 size={16} className={gen.status === 'done' ? '' : 'animate-spin'} />
            {gen.status === 'analyzing'
              ? (gen.statusText || '正在分析您的出行需求...')
              : gen.status === 'generating'
                ? (gen.statusText || '正在生成行程（航班、酒店、会议衔接）...')
                : gen.status === 'done'
                  ? '行程已生成 ✓'
                  : '生成失败'}
          </div>
          {gen.text ? (
            <pre className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-primary-900 bg-white/60 rounded-lg p-3 mt-1 max-h-80 overflow-auto">
              {gen.text}
            </pre>
          ) : (
            gen.status !== 'done' && (
              <div className="mt-1 text-[13px] text-primary-700/80">后台持续生成中，切换菜单不中断，完成后自动更新…</div>
            )
          )}
          {gen.status === 'error' && (
            <div className="text-red-600 mt-1">{gen.error || '生成失败'}</div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        {loading ? (
          <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={26} /></div>
        ) : trips.length === 0 ? (
          <EmptyState
            icon={<Plane size={24} />}
            title="还没有行程"
            description="用一句话描述出行需求，AI 帮你生成完整差旅计划"
            action={{ label: '创建第一个行程', onClick: () => setShowGenerate(true) }}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 max-w-6xl">
            {trips.map((trip, idx) => (
              <div
                key={trip.trip_id}
                className="card card-hover cursor-pointer overflow-hidden group"
                onClick={() => navigate(`/trips/${trip.trip_id}`)}
              >
                {/* Cover */}
                <div className={`h-20 bg-gradient-to-br ${GRADIENTS[idx % GRADIENTS.length]} relative px-5 pt-4`}>
                  <div className="flex items-center justify-between">
                    <Badge tone="primary" className="bg-white/15 border-white/20 text-white backdrop-blur-sm">
                      <Plane size={11} /> {trip.destination || '出差'}
                    </Badge>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(trip.trip_id); }}
                      className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/15 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <div className="absolute -bottom-5 left-5 w-10 h-10 rounded-xl bg-white shadow-md border border-gray-100 flex items-center justify-center">
                    <MapPin size={18} className="text-primary-500" />
                  </div>
                </div>

                {/* Body */}
                <div className="pt-8 px-5 pb-4">
                  <h3 className="font-semibold text-ink-900 truncate">{trip.title || '未命名行程'}</h3>
                  <div className="flex items-center gap-3 mt-2 text-[13px] text-ink-600">
                    <span className="flex items-center gap-1"><Calendar size={13} className="text-ink-400" />{trip.start_date || '-'}</span>
                    <span className="text-ink-400">→</span>
                    <span className="flex items-center gap-1">{trip.end_date || '-'}</span>
                  </div>

                  {trip.days?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {trip.days.map((d, i) => (
                        <span key={i} className="text-[11px] bg-gray-100 text-ink-600 px-2 py-0.5 rounded-md">
                          Day {i + 1} · {d.activities?.length || 0} 项
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="hairline mt-4 pt-3 flex items-center justify-between">
                    <span className="text-xs text-ink-400">查看详情</span>
                    <ArrowRight size={14} className="text-primary-400 group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showGenerate && (
        <ModalForm
          isOpen={showGenerate}
          onClose={() => setShowGenerate(false)}
          title="规划新行程"
          submitText="开始规划"
          fields={[
            {
              name: 'query',
              label: '行程需求',
              type: 'textarea',
              placeholder: '例：9月15号广州飞北京出差，16号拜访国贸客户，17号下午返程',
              rule: { required: true, message: '请描述行程需求' },
            },
          ]}
          onSubmit={handleGenerate}
        />
      )}
    </div>
  );
}
