<template>
  <div style="display:flex;min-height:100vh;">
    <Sidebar />
    <div style="margin-left:240px;flex:1;min-height:100vh;overflow-y:auto;">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </div>
  </div>
</template>

<script setup>
import Sidebar from '@/components/layout/Sidebar.vue'
</script>
