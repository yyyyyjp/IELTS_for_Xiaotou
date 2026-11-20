import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: () => import('./views/HomeView.vue') },
    { path: '/read', name: 'passages', component: () => import('./views/PassagesView.vue') },
    {
      path: '/read/:id',
      name: 'read',
      component: () => import('./views/ReaderView.vue'),
      props: true,
      meta: { immersive: true },
    },
    { path: '/dictate', name: 'dictate', component: () => import('./views/DictationView.vue') },
    { path: '/vocab', name: 'vocab', component: () => import('./views/VocabView.vue') },
    { path: '/stats', name: 'stats', component: () => import('./views/StatsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.path !== from.path) return { top: 0 }
    return {}
  },
})

export default router
