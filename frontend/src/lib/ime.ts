/** Guard custom Enter-to-submit shortcuts while an IME composition is active (including Safari keyCode 229 ordering). */
export function isImeComposing(event: {
  nativeEvent?: { isComposing?: boolean; keyCode?: number }
  keyCode?: number
}): boolean {
  return Boolean(
    event.nativeEvent?.isComposing ||
      event.nativeEvent?.keyCode === 229 ||
      event.keyCode === 229,
  )
}
