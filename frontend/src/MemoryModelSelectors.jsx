import { Field } from './components/console'
import { Input } from '@/components/ui/input'

export default function MemoryModelSelectors({ config, update, providers, disabled }) {
  return <fieldset className="form-grid border-0 m-0 p-0" disabled={disabled}>
    {['embedding', 'rerank'].map(purpose => {
      const selection = config[purpose]
      return <div className="memory-model-fields" key={purpose}>
        <Field label={`${purpose === 'embedding' ? 'Embedding 嵌入' : 'Rerank 重排'}供应商`} id={`memory-${purpose}-provider`} hint={purpose === 'embedding' ? '开启长期记忆前必须配置。' : '可选，关闭时使用初步检索顺序。'}>
          <select className="provider-select" id={`memory-${purpose}-provider`} value={selection.provider_id} onChange={event => { const provider = providers.find(item => item.id === event.target.value); update(purpose, { provider_id: event.target.value, model: provider?.default_model || '' }) }}><option value="">{purpose === 'embedding' ? '选择嵌入供应商' : '不使用重排'}</option>{providers.filter(item => item.purpose === purpose).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        </Field>
        <Field label={`${purpose === 'embedding' ? 'Embedding' : 'Rerank'} 模型名称`} id={`memory-${purpose}-model`}>
          <Input id={`memory-${purpose}-model`} disabled={!selection.provider_id} value={selection.model} maxLength={200} onChange={event => update(purpose, { ...selection, model: event.target.value })} placeholder={purpose === 'rerank' ? '模型名称或 Xinference 部署 UID' : '填写服务提供的嵌入模型名称'} />
        </Field>
      </div>
    })}
  </fieldset>
}
