import { useState, useEffect } from 'react';
import { Loader2, Plus, Trash2, Star, Save, KeyRound, CheckCircle2, XCircle } from 'lucide-react';
import { PageHeader, Card, Button, Badge } from '../components';
import { listModels, updateModels, getLLMConfig, updateLLMConfig, isAdmin } from '../api/auth';

export default function AdminPage() {
  const [models, setModels] = useState([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [llmCfg, setLlmCfg] = useState(null);
  const [newBaseUrl, setNewBaseUrl] = useState('');
  const [newApiKey, setNewApiKey] = useState('');
  const [newModel, setNewModel] = useState({ model_id: '', label: '' });
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [llmEditable, setLlmEditable] = useState(false); // 聚焦后才可编辑，防浏览器自动填充
  const admin = isAdmin();

  useEffect(() => {
    (async () => {
      try {
        const [m, cfg] = await Promise.all([listModels(), admin ? getLLMConfig() : Promise.resolve(null)]);
        setModels(m.models || []);
        setDefaultModel(m.default_model || '');
        setLlmCfg(cfg);
      } catch (err) {
        setMessage('加载配置失败: ' + err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [admin]);

  const flash = (msg) => {
    setMessage(msg);
    setTimeout(() => setMessage(''), 2500);
  };

  const saveModels = async () => {
    try {
      await updateModels({ available_models: models, default_model: defaultModel });
      flash('模型列表已保存');
    } catch (err) {
      flash('保存失败: ' + err.message);
    }
  };

  const saveLLM = async () => {
    try {
      const patch = {};
      if (newBaseUrl.trim()) patch.llm_base_url = newBaseUrl.trim();
      if (newApiKey.trim()) patch.llm_api_key = newApiKey.trim();
      if (!Object.keys(patch).length) { flash('请先填写要修改的配置'); return; }
      const res = await updateLLMConfig(patch);
      setLlmCfg(res);
      setNewBaseUrl('');
      setNewApiKey('');
      flash('LLM 配置已更新并立即生效');
    } catch (err) {
      flash('更新失败: ' + err.message);
    }
  };

  if (loading) return <div className="flex justify-center py-24"><Loader2 className="animate-spin text-ink-400" size={24} /></div>;

  if (!admin) {
    return (
      <div className="h-full flex flex-col px-6 py-5">
        <PageHeader title="系统管理" subtitle="仅管理员可访问" />
        <Card><div className="text-center py-14 text-ink-400 text-sm">需要管理员权限，请使用管理员账号登录</div></Card>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader title="系统管理" subtitle="模型切换与 LLM 服务配置，修改立即生效" />
      {message && (
        <div className="mb-4 max-w-3xl mx-auto w-full text-[13px] text-primary-700 bg-primary-50 border border-primary-100 rounded-lg px-3 py-2">{message}</div>
      )}

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-3xl mx-auto space-y-5">
          {/* LLM 服务配置 */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-ink-900 flex items-center gap-2">
                <KeyRound size={15} className="text-primary-500" /> LLM 服务配置
              </h3>
              {llmCfg && (
                <Badge tone={llmCfg.llm_available ? 'green' : 'red'}>
                  {llmCfg.llm_available ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                  {llmCfg.llm_available ? '服务可用' : '未配置（降级模式）'}
                </Badge>
              )}
            </div>
            {llmCfg && (
              <div className="grid grid-cols-2 gap-3 text-sm mb-4">
                <div className="bg-gray-50/70 rounded-lg px-3 py-2">
                  <div className="text-[11px] text-ink-400">接口地址</div>
                  <div className="text-[13px] text-ink-600 truncate font-mono">{llmCfg.llm_base_url || '-'}</div>
                </div>
                <div className="bg-gray-50/70 rounded-lg px-3 py-2">
                  <div className="text-[11px] text-ink-400">API Key</div>
                  <div className="text-[13px] text-ink-600 font-mono">{llmCfg.llm_api_key_masked || '未配置'}</div>
                </div>
              </div>
            )}
            <div className="space-y-3" onClick={() => setLlmEditable(true)}>
              <input
                value={newBaseUrl}
                onChange={(e) => setNewBaseUrl(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400"
                placeholder="OpenAI 兼容接口地址，如 https://tokenhub.tencentmaas.com/v1（点击输入框开始编辑）"
                autoComplete="off"
                name="llm-endpoint-no-autofill"
                readOnly={!llmEditable}
                onFocus={() => setLlmEditable(true)}
              />
              <input
                type="password"
                value={newApiKey}
                onChange={(e) => setNewApiKey(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-primary-400"
                placeholder="API Key（留空表示不修改；点击输入框开始编辑）"
                autoComplete="new-password"
                name="llm-apikey-no-autofill"
                readOnly={!llmEditable}
                onFocus={() => setLlmEditable(true)}
              />
              <div className="flex justify-end">
                <Button type="primary" onClick={saveLLM}><Save size={14} /> 保存并生效</Button>
              </div>
            </div>
            <p className="text-xs text-ink-400 mt-3">修改立即生效（无需重启服务）；Key 保存后仅脱敏显示。</p>
          </Card>

          {/* 模型列表管理 */}
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-ink-900 mb-4">可用模型（前端选择器数据源）</h3>
            <div className="space-y-2 mb-4">
              {models.map((m) => (
                <div key={m.model_id} className="flex items-center gap-2 bg-gray-50/70 rounded-lg px-3 py-2">
                  <button
                    onClick={() => setDefaultModel(m.model_id)}
                    className={`shrink-0 flex items-center gap-1 text-xs px-2 py-1 rounded-md transition-colors ${
                      defaultModel === m.model_id
                        ? 'bg-amber-100 text-amber-700 font-medium'
                        : 'text-ink-400 hover:text-amber-600'
                    }`}
                    title={defaultModel === m.model_id ? '当前默认模型' : '设为默认'}
                  >
                    <Star size={12} fill={defaultModel === m.model_id ? 'currentColor' : 'none'} />
                    {defaultModel === m.model_id ? '默认' : '设默认'}
                  </button>
                  <input
                    value={m.label}
                    onChange={(e) => setModels(models.map((x) => x.model_id === m.model_id ? { ...x, label: e.target.value } : x))}
                    className="w-28 px-2 py-1 text-sm bg-white border border-gray-200 rounded-md"
                  />
                  <span className="text-ink-300">/</span>
                  <input
                    value={m.model_id}
                    onChange={(e) => setModels(models.map((x, i) => i === models.indexOf(m) ? { ...x, model_id: e.target.value } : x))}
                    className="flex-1 px-2 py-1 text-sm font-mono bg-white border border-gray-200 rounded-md"
                  />
                  <button
                    onClick={() => setModels(models.filter((x) => x !== m))}
                    className="p-1.5 text-ink-400 hover:text-red-500 transition-colors"
                    title="删除"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2 mb-4">
              <input
                value={newModel.label}
                onChange={(e) => setNewModel({ ...newModel, label: e.target.value })}
                className="w-28 px-2 py-1.5 text-sm bg-white border border-gray-200 rounded-md"
                placeholder="显示名"
              />
              <input
                value={newModel.model_id}
                onChange={(e) => setNewModel({ ...newModel, model_id: e.target.value })}
                className="flex-1 px-2 py-1.5 text-sm font-mono bg-white border border-gray-200 rounded-md"
                placeholder="模型 ID（透传给服务商）"
              />
              <Button
                type="secondary"
                onClick={() => {
                  if (!newModel.model_id.trim() || !newModel.label.trim()) return;
                  setModels([...models, { model_id: newModel.model_id.trim(), label: newModel.label.trim() }]);
                  setNewModel({ model_id: '', label: '' });
                }}
              >
                <Plus size={14} /> 添加
              </Button>
            </div>

            <div className="flex justify-end">
              <Button type="primary" onClick={saveModels}><Save size={14} /> 保存模型列表</Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
