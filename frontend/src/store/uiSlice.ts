import { createSlice } from '@reduxjs/toolkit'

interface UiState {
  selectedHost: string | null
}

const initialState: UiState = {
  selectedHost: null,
}

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setSelectedHost: (state, action: { payload: string | null }) => {
      state.selectedHost = action.payload
    },
  },
})

export const { setSelectedHost } = uiSlice.actions
export default uiSlice.reducer
