<script setup>
import { onMounted, ref } from 'vue'
import { listFaq } from '../api'
import ReportPanel from './ReportPanel.vue'

const props = defineProps({
  profile: { type: Object, required: true },
  runtime: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update:profile', 'ask', 'report-result'])

const QUICK = [
  '最近三天咳嗽有黄痰，该挂什么科？',
  '体检报告显示总胆固醇偏高怎么办？',
  '孩子发烧 38.9℃ 需要马上去医院吗？',
  '空腹抽血检查需要空腹多久？',
  '反复头痛一个月了，严重吗？',
]

const localProfile = ref({ ...props.profile })
const faqs = ref([])
const openFaq = ref(-1)

function syncProfile() {
  emit('update:profile', { ...localProfile.value })
}

onMounted(async () => {
  try {
    faqs.value = await listFaq('', 8)
  } catch {
    faqs.value = []
  }
})
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">康</div>
      <div>
        <div class="brand-name">智能问诊客服</div>
        <div class="brand-sub">康云互联网医院</div>
      </div>
    </div>

    <div class="sidebar-scroll">
      <ReportPanel @result="emit('report-result', $event)" />

      <div class="card">
        <div class="card-title">患者信息（选填）</div>
        <div class="row">
          <div class="field">
            <label>年龄</label>
            <input v-model="localProfile.age" type="number" placeholder="35" @change="syncProfile" />
          </div>
          <div class="field">
            <label>性别</label>
            <select v-model="localProfile.gender" @change="syncProfile">
              <option value="">未选择</option>
              <option value="男">男</option>
            <option value="女">女</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>症状持续时间</label>
          <input v-model="localProfile.duration" type="text" placeholder="如：3天" @change="syncProfile" />
        </div>
        <div class="field">
          <label>既往病史</label>
          <input v-model="localProfile.history" type="text" placeholder="如：高血压、糖尿病" @change="syncProfile" />
        </div>
        <div class="field" style="margin-bottom: 0">
          <label>过敏史</label>
          <input v-model="localProfile.allergy" type="text" placeholder="如：青霉素" @change="syncProfile" />
        </div>
      </div>

      <div class="card">
        <div class="card-title">快捷提问</div>
        <button v-for="q in QUICK" :key="q" class="chip" @click="emit('ask', q)">
          {{ q }}
        </button>
      </div>

      <div class="card">
        <div class="card-title">常见问题</div>
        <div v-for="(f, i) in faqs" :key="i" class="faq-item">
          <div class="faq-q" @click="openFaq = openFaq === i ? -1 : i">
            {{ f.question }}
          </div>
          <div v-if="openFaq === i" class="faq-a">{{ f.answer }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">运行状态</div>
        <div class="runtime">
          <div>模型引擎：<b>{{ runtime.llm_engine || '-' }}</b></div>
          <div>向量库：<b>{{ runtime.vector_backend || '-' }}</b></div>
          <div>嵌入模型：<b>{{ runtime.embedding_backend || '-' }}</b></div>
        </div>
      </div>
    </div>
  </aside>
</template>
