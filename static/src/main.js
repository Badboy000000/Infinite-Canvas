import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// 挂载到 #app 容器(与 legacy HTML 页面并行 · 不冲突)
const app = createApp(App)
app.use(router)
app.use(createPinia())
app.mount('#app')