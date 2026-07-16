<template>


<div>


<Sidebar/>


<div class="content">


<router-view/>


</div>


</div>


</template>


<script setup>

import Sidebar from '@/components/Sidebar.vue'


</script>



<style scoped>

.content{


margin-left:250px;


min-height:100vh;


background:#f8fafc;


}


</style>