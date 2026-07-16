<template>
  <router-view />
</template>

<script setup>
import { useUserStore } from '@/stores/user'
useUserStore().tryRestore()
</script>
