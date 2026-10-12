<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import TriageCard from './TriageCard.vue'

const props = defineProps({
  role: { type: String, required: true },
  content: { type: String, default: '' },
  triage: { type: Object, default: null },
  evidence: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
})

const html = computed(() => {
  if (props.role !== 'assistant') return ''
  return marked.parse(props.content || '', { breaks: true, gfm: true })
})
</script>

<template>
  <div class="msg" :class="role">
    <div class="avatar" :class="role === 'user' ? 'user' : 'bot'">
      {{ role === 'user' ? '我' : '康' }}
    </div>

    <div>
      <div v-if="triage" class="bubble" style="margin-bottom: 10px">
        <TriageCard :triage="triage" />
      </div>

      <div class="bubble" :class="{ cursor: streaming }">
      <div v-if="role === 'assistant'" v-html="html" />
      <template v-else>{{ content }}</template>
      </div>

      <details v-if="evidence && evidence.length" class="evidence">
      <summary>参考依据（{{ evidence.length }} 条知识库片段）</summary>
      <ul>
        <li v-for="(e, i) in evidence" :key="i">
          《{{ e.title }}》· 来源：{{ e.source }} · 相关度 {{ e.score }}
          <div style="opacity: .8">{{ e.snippet }}</div>
        </li>
      </ul>
      </details>
    </div>
  </div>
</template>
