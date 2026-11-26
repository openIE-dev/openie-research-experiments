/* SPDX-License-Identifier: Apache-2.0
 * Native Vulkan 1.x Compute + Co-Scheduled CPU+GPU HeteroMosaic runtime for `waiOS` 256x128.
 * Dynamically selects physical discrete/integrated GPU (excluding software `llvmpipe` when real GPU exists).
 */

#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>

#define WAI_ROWS 256
#define WAI_COLS 128
#define WAI_PAIRS 64

typedef struct {
    int initialized;
    VkInstance instance;
    VkPhysicalDevice phys;
    VkDevice device;
    uint32_t queue_family;
    VkQueue queue;
    char device_name[256];
    uint32_t api_version;
} VkCtx;

static VkCtx g_vk = {0};

static int find_host_coherent_mem(VkPhysicalDevice phys, uint32_t type_bits, uint32_t *out_idx) {
    VkPhysicalDeviceMemoryProperties mp;
    vkGetPhysicalDeviceMemoryProperties(phys, &mp);
    VkMemoryPropertyFlags req = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++) {
        if ((type_bits & (1U << i)) && ((mp.memoryTypes[i].propertyFlags & req) == req)) {
            *out_idx = i;
            return 0;
        }
    }
    return -1;
}

int waios_vk_init(char *out_name, int name_cap) {
    if (g_vk.initialized) {
        if (out_name && name_cap > 0) {
            strncpy(out_name, g_vk.device_name, (size_t)(name_cap - 1));
            out_name[name_cap - 1] = 0;
        }
        return 0;
    }

    VkApplicationInfo app = {0};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "waios-mosaic-vulkan";
    app.apiVersion = VK_API_VERSION_1_1;

    VkInstanceCreateInfo ici = {0};
    ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ici.pApplicationInfo = &app;
    if (vkCreateInstance(&ici, NULL, &g_vk.instance) != VK_SUCCESS) return -1;

    uint32_t dev_cnt = 0;
    if (vkEnumeratePhysicalDevices(g_vk.instance, &dev_cnt, NULL) != VK_SUCCESS || dev_cnt == 0) return -2;
    VkPhysicalDevice *devs = (VkPhysicalDevice *)calloc(dev_cnt, sizeof(VkPhysicalDevice));
    vkEnumeratePhysicalDevices(g_vk.instance, &dev_cnt, devs);

    int best_idx = -1;
    int best_score = -1;
    for (uint32_t i = 0; i < dev_cnt; i++) {
        VkPhysicalDeviceProperties pr;
        vkGetPhysicalDeviceProperties(devs[i], &pr);
        int score = 1;
        if (pr.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) score = 100;
        else if (pr.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU) score = 90;
        if (strstr(pr.deviceName, "llvmpipe") != NULL) score = 5;
        if (score > best_score) {
            best_score = score;
            best_idx = (int)i;
        }
    }
    if (best_idx < 0) { free(devs); return -3; }
    g_vk.phys = devs[best_idx];
    free(devs);

    VkPhysicalDeviceProperties pr;
    vkGetPhysicalDeviceProperties(g_vk.phys, &pr);
    strncpy(g_vk.device_name, pr.deviceName, sizeof(g_vk.device_name) - 1);
    g_vk.api_version = pr.apiVersion;

    uint32_t qf_cnt = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &qf_cnt, NULL);
    VkQueueFamilyProperties *qfs = (VkQueueFamilyProperties *)calloc(qf_cnt, sizeof(VkQueueFamilyProperties));
    vkGetPhysicalDeviceQueueFamilyProperties(g_vk.phys, &qf_cnt, qfs);
    int qf_idx = -1;
    for (uint32_t i = 0; i < qf_cnt; i++) {
        if (qfs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { qf_idx = (int)i; break; }
    }
    free(qfs);
    if (qf_idx < 0) return -4;
    g_vk.queue_family = (uint32_t)qf_idx;

    float prio = 1.0f;
    VkDeviceQueueCreateInfo qci = {0};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = g_vk.queue_family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &prio;

    VkDeviceCreateInfo dci = {0};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    if (vkCreateDevice(g_vk.phys, &dci, NULL, &g_vk.device) != VK_SUCCESS) return -5;
    vkGetDeviceQueue(g_vk.device, g_vk.queue_family, 0, &g_vk.queue);
    g_vk.initialized = 1;

    if (out_name && name_cap > 0) {
        strncpy(out_name, g_vk.device_name, (size_t)(name_cap - 1));
        out_name[name_cap - 1] = 0;
    }
    return 0;
}

static int create_storage_buf(VkDeviceSize sz, VkBuffer *buf, VkDeviceMemory *mem, void **mapped) {
    VkBufferCreateInfo bci = {0};
    bci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bci.size = sz;
    bci.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(g_vk.device, &bci, NULL, buf) != VK_SUCCESS) return -1;

    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(g_vk.device, *buf, &mr);
    uint32_t mtype = 0;
    if (find_host_coherent_mem(g_vk.phys, mr.memoryTypeBits, &mtype) != 0) return -2;

    VkMemoryAllocateInfo mai = {0};
    mai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    mai.allocationSize = mr.size;
    mai.memoryTypeIndex = mtype;
    if (vkAllocateMemory(g_vk.device, &mai, NULL, mem) != VK_SUCCESS) return -3;
    if (vkBindBufferMemory(g_vk.device, *buf, *mem, 0) != VK_SUCCESS) return -4;
    if (vkMapMemory(g_vk.device, *mem, 0, sz, 0, mapped) != VK_SUCCESS) return -5;
    return 0;
}

typedef struct {
    int mode; /* 0: T-MAC LUT, 1: 2-bit bit-sliced popcount */
    int row_start;
    int row_end;
    const int8_t *weights;
    const int8_t *acts;
    int32_t *out;
} CpuHalfTask;

static inline uint8_t w_code2(int8_t w) {
    return (w == 1) ? 1U : ((w == -1) ? 2U : 0U);
}

static void *cpu_half_worker(void *arg) {
    CpuHalfTask *t = (CpuHalfTask *)arg;
    if (t->mode == 0) {
        int32_t lut[WAI_PAIRS][16];
        for (int g = 0; g < WAI_PAIRS; g++) {
            int32_t a0 = (int32_t)t->acts[2 * g], a1 = (int32_t)t->acts[2 * g + 1];
            for (int cd = 0; cd < 16; cd++) {
                int c0 = cd & 3, c1 = (cd >> 2) & 3;
                lut[g][cd] = ((c0 == 1) ? a0 : ((c0 == 2) ? -a0 : 0))
                           + ((c1 == 1) ? a1 : ((c1 == 2) ? -a1 : 0));
            }
        }
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            int32_t acc = 0;
            for (int g = 0; g < WAI_PAIRS; g++) {
                uint8_t cd = (uint8_t)(w_code2(wrow[2 * g]) | (w_code2(wrow[2 * g + 1]) << 2));
                acc += lut[g][cd];
            }
            t->out[r] = acc;
        }
    } else {
        uint64_t act_neg[2] = {0ULL, 0ULL};
        uint64_t act_plane[7][2];
        memset(act_plane, 0, sizeof(act_plane));
        for (int w = 0; w < 2; w++) {
            for (int b = 0; b < 64; b++) {
                int a = (int)t->acts[w * 64 + b];
                int mag = a < 0 ? -a : a;
                if (a < 0) act_neg[w] |= (1ULL << b);
                for (int p = 0; p < 7; p++) if ((mag >> p) & 1) act_plane[p][w] |= (1ULL << b);
            }
        }
        for (int r = t->row_start; r < t->row_end; r++) {
            const int8_t *wrow = t->weights + r * WAI_COLS;
            uint64_t pm[2] = {0ULL, 0ULL}, nm[2] = {0ULL, 0ULL};
            for (int w = 0; w < 2; w++) {
                for (int b = 0; b < 64; b++) {
                    int8_t v = wrow[w * 64 + b];
                    if (v == 1) pm[w] |= (1ULL << b);
                    else if (v == -1) nm[w] |= (1ULL << b);
                }
            }
            uint64_t eadd0 = (pm[0] & ~act_neg[0]) | (nm[0] & act_neg[0]);
            uint64_t eadd1 = (pm[1] & ~act_neg[1]) | (nm[1] & act_neg[1]);
            uint64_t esub0 = (pm[0] & act_neg[0]) | (nm[0] & ~act_neg[0]);
            uint64_t esub1 = (pm[1] & act_neg[1]) | (nm[1] & ~act_neg[1]);
            int32_t acc = 0;
            for (int p = 0; p < 7; p++) {
                int pa = __builtin_popcountll(eadd0 & act_plane[p][0]) + __builtin_popcountll(eadd1 & act_plane[p][1]);
                int ps = __builtin_popcountll(esub0 & act_plane[p][0]) + __builtin_popcountll(esub1 & act_plane[p][1]);
                acc += (pa - ps) << p;
            }
            t->out[r] = acc;
        }
    }
    return NULL;
}

/* If gpu_cut == 256 -> pure GPU compute; if 0 < gpu_cut < 256 -> co-scheduled GPU [0..gpu_cut) + CPU pthreads [gpu_cut..256) */
int waios_vk_run_matvec(
    const char *spv_path,
    const int8_t *weights,
    const int8_t *acts,
    int gpu_cut,
    int32_t *out_256
) {
    if (waios_vk_init(NULL, 0) != 0) return -10;
    if (gpu_cut < 1) gpu_cut = 1;
    if (gpu_cut > WAI_ROWS) gpu_cut = WAI_ROWS;

    FILE *fp = fopen(spv_path, "rb");
    if (!fp) return -11;
    fseek(fp, 0, SEEK_END);
    long spv_len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    uint32_t *spv_code = (uint32_t *)malloc((size_t)spv_len);
    if (fread(spv_code, 1, (size_t)spv_len, fp) != (size_t)spv_len) { fclose(fp); free(spv_code); return -12; }
    fclose(fp);

    VkShaderModuleCreateInfo smci = {0};
    smci.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    smci.codeSize = (size_t)spv_len;
    smci.pCode = spv_code;
    VkShaderModule shader = VK_NULL_HANDLE;
    if (vkCreateShaderModule(g_vk.device, &smci, NULL, &shader) != VK_SUCCESS) { free(spv_code); return -13; }
    free(spv_code);

    VkBuffer b_w, b_a, b_o;
    VkDeviceMemory m_w, m_a, m_o;
    void *p_w = NULL, *p_a = NULL, *p_o = NULL;
    VkDeviceSize sz_w = WAI_ROWS * WAI_COLS * sizeof(int32_t);
    VkDeviceSize sz_a = WAI_COLS * sizeof(int32_t);
    VkDeviceSize sz_o = WAI_ROWS * sizeof(int32_t);
    if (create_storage_buf(sz_w, &b_w, &m_w, &p_w) != 0) return -14;
    if (create_storage_buf(sz_a, &b_a, &m_a, &p_a) != 0) return -15;
    if (create_storage_buf(sz_o, &b_o, &m_o, &p_o) != 0) return -16;

    int32_t *wi = (int32_t *)p_w;
    int32_t *ai = (int32_t *)p_a;
    int32_t *oi = (int32_t *)p_o;
    for (int i = 0; i < WAI_ROWS * WAI_COLS; i++) wi[i] = (int32_t)weights[i];
    for (int c = 0; c < WAI_COLS; c++) ai[c] = (int32_t)acts[c];
    memset(oi, 0, (size_t)sz_o);

    VkDescriptorSetLayoutBinding binds[3] = {0};
    for (uint32_t i = 0; i < 3; i++) {
        binds[i].binding = i;
        binds[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        binds[i].descriptorCount = 1;
        binds[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    }
    VkDescriptorSetLayoutCreateInfo dslci = {0};
    dslci.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    dslci.bindingCount = 3;
    dslci.pBindings = binds;
    VkDescriptorSetLayout dsl;
    vkCreateDescriptorSetLayout(g_vk.device, &dslci, NULL, &dsl);

    VkPushConstantRange pcr = {0};
    pcr.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    pcr.offset = 0;
    pcr.size = 3 * sizeof(int32_t);

    VkPipelineLayoutCreateInfo plci = {0};
    plci.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    plci.setLayoutCount = 1;
    plci.pSetLayouts = &dsl;
    plci.pushConstantRangeCount = 1;
    plci.pPushConstantRanges = &pcr;
    VkPipelineLayout playout;
    vkCreatePipelineLayout(g_vk.device, &plci, NULL, &playout);

    VkComputePipelineCreateInfo cpci = {0};
    cpci.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
    cpci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    cpci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    cpci.stage.module = shader;
    cpci.stage.pName = "main";
    cpci.layout = playout;
    VkPipeline pipe;
    vkCreateComputePipelines(g_vk.device, VK_NULL_HANDLE, 1, &cpci, NULL, &pipe);

    VkDescriptorPoolSize dps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3};
    VkDescriptorPoolCreateInfo dpci = {0};
    dpci.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    dpci.maxSets = 1;
    dpci.poolSizeCount = 1;
    dpci.pPoolSizes = &dps;
    VkDescriptorPool dpool;
    vkCreateDescriptorPool(g_vk.device, &dpci, NULL, &dpool);

    VkDescriptorSetAllocateInfo dsai = {0};
    dsai.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    dsai.descriptorPool = dpool;
    dsai.descriptorSetCount = 1;
    dsai.pSetLayouts = &dsl;
    VkDescriptorSet dset;
    vkAllocateDescriptorSets(g_vk.device, &dsai, &dset);

    VkDescriptorBufferInfo dbis[3] = {
        {b_w, 0, sz_w},
        {b_a, 0, sz_a},
        {b_o, 0, sz_o}
    };
    VkWriteDescriptorSet wds[3] = {0};
    for (uint32_t i = 0; i < 3; i++) {
        wds[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        wds[i].dstSet = dset;
        wds[i].dstBinding = i;
        wds[i].descriptorCount = 1;
        wds[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        wds[i].pBufferInfo = &dbis[i];
    }
    vkUpdateDescriptorSets(g_vk.device, 3, wds, 0, NULL);

    VkCommandPoolCreateInfo cmpci = {0};
    cmpci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    cmpci.queueFamilyIndex = g_vk.queue_family;
    VkCommandPool cpool;
    vkCreateCommandPool(g_vk.device, &cmpci, NULL, &cpool);

    VkCommandBufferAllocateInfo cbai = {0};
    cbai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cbai.commandPool = cpool;
    cbai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cbai.commandBufferCount = 1;
    VkCommandBuffer cmd;
    vkAllocateCommandBuffers(g_vk.device, &cbai, &cmd);

    VkCommandBufferBeginInfo cbbi = {0};
    cbbi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    cbbi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    vkBeginCommandBuffer(cmd, &cbbi);
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipe);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, playout, 0, 1, &dset, 0, NULL);
    int32_t pc_vals[3] = {0, gpu_cut, WAI_COLS};
    vkCmdPushConstants(cmd, playout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(pc_vals), pc_vals);
    vkCmdDispatch(cmd, (uint32_t)((gpu_cut + 63) / 64), 1, 1);

    VkMemoryBarrier mb = {0};
    mb.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER;
    mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    mb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(
        cmd,
        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
        VK_PIPELINE_STAGE_HOST_BIT,
        0,
        1, &mb,
        0, NULL,
        0, NULL
    );
    vkEndCommandBuffer(cmd);

    VkFenceCreateInfo fci = {0};
    fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence;
    vkCreateFence(g_vk.device, &fci, NULL, &fence);

    VkSubmitInfo si = {0};
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;
    si.pCommandBuffers = &cmd;

    /* Submit GPU work asynchronously FIRST, then run CPU pthreads concurrently on [gpu_cut..256)! */
    if (vkQueueSubmit(g_vk.queue, 1, &si, fence) != VK_SUCCESS) return -17;

    int32_t cpu_out[WAI_ROWS] = {0};
    if (gpu_cut < WAI_ROWS) {
        int mid = gpu_cut + (WAI_ROWS - gpu_cut) / 2;
        pthread_t th[2];
        CpuHalfTask tasks[2] = {
            {0, gpu_cut, mid, weights, acts, cpu_out},
            {1, mid, WAI_ROWS, weights, acts, cpu_out}
        };
        pthread_create(&th[0], NULL, cpu_half_worker, &tasks[0]);
        pthread_create(&th[1], NULL, cpu_half_worker, &tasks[1]);
        pthread_join(th[0], NULL);
        pthread_join(th[1], NULL);
    }

    vkWaitForFences(g_vk.device, 1, &fence, VK_TRUE, 5000000000ULL);

    for (int r = 0; r < gpu_cut; r++) out_256[r] = oi[r];
    for (int r = gpu_cut; r < WAI_ROWS; r++) out_256[r] = cpu_out[r];

    vkDestroyFence(g_vk.device, fence, NULL);
    vkDestroyCommandPool(g_vk.device, cpool, NULL);
    vkDestroyDescriptorPool(g_vk.device, dpool, NULL);
    vkDestroyPipeline(g_vk.device, pipe, NULL);
    vkDestroyPipelineLayout(g_vk.device, playout, NULL);
    vkDestroyDescriptorSetLayout(g_vk.device, dsl, NULL);
    vkDestroyShaderModule(g_vk.device, shader, NULL);
    vkUnmapMemory(g_vk.device, m_w); vkDestroyBuffer(g_vk.device, b_w, NULL); vkFreeMemory(g_vk.device, m_w, NULL);
    vkUnmapMemory(g_vk.device, m_a); vkDestroyBuffer(g_vk.device, b_a, NULL); vkFreeMemory(g_vk.device, m_a, NULL);
    vkUnmapMemory(g_vk.device, m_o); vkDestroyBuffer(g_vk.device, b_o, NULL); vkFreeMemory(g_vk.device, m_o, NULL);
    return 0;
}
