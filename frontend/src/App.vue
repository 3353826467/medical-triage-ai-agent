<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { chatStream, runtime as fetchRuntime } from './api'
import ChatMessage from './components/ChatMessage.vue'
import SidePanel from './components/SidePanel.vue'

const messages = ref([
  {
    role: 'assistant',
    content:
      '你好，我是智能客服「小康」👩‍⚕️\n\n请描述你的症状或问题，我可以帮你做**智能分诊**、**症状科普**和**报告解读**。\n\n例如：**咳嗽三天有黄痰，该挂什么科？**',
  },
])
const input = ref('')
const sessionId = ref('')
const profile = ref({})
const loading = ref(false)
const runtimeInfo = ref({})
const scrollRef = ref(null)

let controller = null

function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(async () => {
  try {
    runtimeInfo.value = await fetchRuntime()
  } catch {
    runtimeInfo.value = {}
  }
})

async function send(text) {
  const content = (text ?? input.value).trim()
  if (!content || loading.value) return

  input.value = ''
  messages.value.push({ role: 'user', content })
  const bot = { role: 'assistant', content: '', streaming: true, evidence: [] }
  messages.value.push(bot)
  loading.value = true
  scrollToBottom()

  controller = new AbortController()

  await chatStream(
    {
      session_id: sessionId.value,
      message: content,
      profile: profile.value,
      stream: true,
      with_evidence: true,
    },
    {
      onMeta: (data) => {
        if (data?.session_id) sessionId.value = data.session_id
        if (Array.isArray(data?.evidence)) bot.evidence = data.evidence
      },
      onDelta: (piece) => {
        bot.content += piece
        scrollToBottom()
      },
      onDone: (data) => {
        bot.streaming = false
        if (data?.triage) bot.triage = data.triage
        loading.value = false
        scrollToBottom()
      },
      onError: (err) => {
        bot.streaming = false
        bot.content += `\n\n> ⚠️ 请求失败：${err.message || err}`
        loading.value = false
      },
    },
    controller.signal,
  )
}

function onReportResult(payload) {
  messages.value.push(payload)
  scrollToBottom()
}

function newSession() {
  sessionId.value = ''
  messages.value = [
    {
      role: 'assistant',
      content: '已开启新的问诊会话，请描述你的症状或问题。',
    },
  ]
}

function onKeydown(e) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="layout">
    <SidePanel
      v-model:profile="profile"
      :runtime="runtimeInfo"
      @ask="send"
      @report-result="onReportResult"
    />

    <main class="main">
      <header class="chat-header">
        <div>
          <h1>智能问诊 AI 客服</h1>
          <p>症状咨询 · 智能分诊 · 报告解读 · 就医服务</p>
        </div>
        <button class="btn" @click="newSession">新建会话</button>
      </header>

      <div ref="scrollRef" class="chat-scroll">
        <div class="chat-inner">
          <ChatMessage
            v-for="(m, i) in messages"
            :key="i"
            :role="m.role"
            :content="m.content"
            :triage="m.triage"
            :evidence="m.evidence"
            :streaming="m.streaming"
          />
        </div>
      </div>

      <div class="composer">
        <div class="composer-inner">
          <textarea
            v-model="input"
            placeholder="描述你的症状，例如：咳嗽三天，有黄痰，晚上加重…（Enter 发送 / Shift+Enter 换行）"
            @keydown="onKeydown"
          />
          <button class="btn btn-primary" :disabled="loading || !input.trim()" @click="send()">
            {{ loading ? '回复中…' : '发送' }}
          </button>
        </div>
        <div class="hint">
          本系统提供的是健康参考信息，不构成诊断；急症请立即拨打 120。
        </div>
      </div>
    </main>
  </div>
</template>
