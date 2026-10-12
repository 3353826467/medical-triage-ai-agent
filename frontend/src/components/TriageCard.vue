<script setup>
import { computed } from 'vue'

const props = defineProps({
  triage: { type: Object, required: true },
})

const URGENCY = {
  emergency: { label: '紧急 · 立即就医', cls: 'u-emergency' },
  urgent: { label: '尽快就诊', cls: 'u-urgent' },
  routine: { label: '门诊择期', cls: 'u-routine' },
  self_care: { label: '居家观察', cls: 'u-self_care' },
}

const PROB = {
  high: { text: '可能性高', cls: 'badge-off' },
  medium: { text: '可能性中', cls: 'badge-off' },
  low: { text: '可能性低', cls: 'badge-ok' },
}

const urgency = computed(() => URGENCY[props.triage.urgency] || URGENCY.routine)
const conditions = computed(() => props.triage.possible_conditions || [])
const advice = computed(() => props.triage.advice || [])
</script>

<template>
  <div class="triage-card" :class="urgency.cls">
    <div class="triage-head">
      <div>
        <div class="triage-dept">{{ triage.department }}</div>
        <div class="triage-alias">
          首诊科室建议
          <span v-if="triage.department_aliases && triage.department_aliases.length">
            · {{ triage.department_aliases.join(' / ') }}
          </span>
        </div>
      </div>
      <span class="badge" :class="urgency.cls === 'u-emergency' ? 'badge-off' : 'badge-ok'">
        {{ urgency.label }}
      </span>
    </div>

    <div class="triage-body">
      <p v-if="triage.urgency_reason" class="triage-reason">{{ triage.urgency_reason }}</p>

      <div v-if="conditions.length">
        <h4>需要排查的情况</h4>
        <ul>
          <li v-for="(c, i) in conditions" :key="i">
            {{ c.name }}
            <span class="badge" :class="(PROB[c.probability] || PROB.low).cls">
              {{ (PROB[c.probability] || PROB.low).text }}
            </span>
            <span v-if="c.reason" class="triage-reason">——{{ c.reason }}</span>
          </li>
        </ul>
      </div>

      <div v-if="advice.length">
        <h4>建议</h4>
        <ul>
          <li v-for="(a, i) in advice" :key="i">{{ a }}</li>
        </ul>
      </div>

      <p v-if="triage.disclaimer" class="triage-reason">{{ triage.disclaimer }}</p>
    </div>
  </div>
</template>
