import { ref } from 'vue'

export type Route =
  | { name: 'auth' }
  | { name: 'dictionaries' }
  | { name: 'study'; dictionaryId: number }
  | { name: 'done'; dictionaryId: number }
  | { name: 'profile' }

export function parsePath(hash: string): Route {
  const path = hash.replace(/^#/, '').replace(/\/+$/, '')
  if (path === '' || path === '/') return { name: 'dictionaries' }
  if (path === '/auth') return { name: 'auth' }
  if (path === '/profile') return { name: 'profile' }
  const study = /^\/study\/(\d+)$/.exec(path)
  if (study) return { name: 'study', dictionaryId: Number(study[1]) }
  const done = /^\/done\/(\d+)$/.exec(path)
  if (done) return { name: 'done', dictionaryId: Number(done[1]) }
  return { name: 'dictionaries' }
}

export function pathOf(route: Route) {
  switch (route.name) {
    case 'auth':
      return '/auth'
    case 'study':
      return `/study/${route.dictionaryId}`
    case 'done':
      return `/done/${route.dictionaryId}`
    case 'profile':
      return '/profile'
    default:
      return '/'
  }
}

export const route = ref<Route>(parsePath(window.location.hash))

window.addEventListener('hashchange', () => {
  route.value = parsePath(window.location.hash)
})

export function navigate(target: Route | string) {
  const path = typeof target === 'string' ? target : pathOf(target)
  if (pathOf(route.value) === path) return
  window.location.hash = path
}

export function replace(target: Route | string) {
  const path = typeof target === 'string' ? target : pathOf(target)
  if (pathOf(route.value) === path) return
  window.history.replaceState(null, '', `#${path}`)
  route.value = parsePath(path)
}
