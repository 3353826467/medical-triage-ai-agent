<script setup>
import { ref } from 'vue'
import { interpretReport, uploadReport } from '../api'

const emit = defineEmits(['result'])

const text = ref('')
const loading = ref(false)
const error = ref('')
const fileInput = ref(null)

const SAMPLE = `血常规检验报告
白细胞 WBC  12.3 ×10^9/L ↑ (参考 3.5-9.5)
血红蛋白 Hb 105 g/L ↓ (参考 130-175)
血小板 PLT  210 ×10^9/L (参考 125-350)
空腹血糖 GLU 7.2 mmol/L ↑ (参考 3.9-6.1)`

async function submit() {
  const content = text.value.trim()
  if (!content || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await interpretReport(content)
    emit('result', { role: 'assistant', content: data.summary, evidence: [] })
    text.value = ''
  } catch (err) {
    error.value = String(err.message || err)
  } finally {
    loading.value = false
  }
}

async function onFileChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  loading.value = true
  error.value = ''
  try {
    const data = await uploadReport(file)
    emit('result', { role: 'assistant', content: data.summary, evidence: [] })
  } catch (err) {
    error.value = String(err.message || err)
  } finally {
    loading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function fillSample() {
  text.value = SAMPLE
}
</script>

<template>
  <div class="card">
    <div class="card-title">报告解读</div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="field">
      <label>粘贴检验 / 影像报告内容</label>
      <textarea v-model="text" placeholder="例如：白细胞 12.3 ×10^9/L ↑，血红蛋白 105 g/L ↓…" />
    </div>

    <div class="row" style="margin-bottom: 8px">
      <button class="btn btn-primary" :disabled="loading || !text.trim()" @click="submit">
        {{ loading ? '解读中…' : '开始解读' }}
      </button>
      <button class="btn" @click="fillSample">填入示例</button>
    </div>

    <div class="field" style="margin-bottom: 0">
      <label>或上传报告文件（txt / md / docx / pdf）</label>
      <input ref="fileInput" type="file" accept=".txt,.md,.docx,.pdf" @change="onFileChange" />
    </div>
  </div>
</template>
