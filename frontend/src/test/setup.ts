// Vitest 全局 setup：jsdom 个别版本未实例化 localStorage，兜底内存实现。
// prefs / token 等模块直接读写 localStorage，测试环境必须可用。
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>()
  const localStorageStub: Storage = {
    get length() {
      return store.size
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  }
  Object.defineProperty(globalThis, 'localStorage', { value: localStorageStub, configurable: true })
  Object.defineProperty(globalThis, 'sessionStorage', { value: localStorageStub, configurable: true })
}

// React 18：act() 需要显式声明测试环境（RTL 未启 globals 时不会自动设置）
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// 未启 globals 时 RTL 不自动注册 cleanup，手动挂载保证用例间 DOM 隔离
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
afterEach(cleanup)
