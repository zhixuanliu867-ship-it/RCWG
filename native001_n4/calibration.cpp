// Finite engineering workloads; never launch without the N4 cgroup/receipt gate.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <unistd.h>
#include <time.h>
using Clock=std::chrono::steady_clock;
static uint64_t checksum=0;
static void cpu(uint64_t n){uint64_t x=17;for(uint64_t i=0;i<n;i++)x=x*6364136223846793005ULL+1442695040888963407ULL;checksum^=x;}
static void memory(size_t bytes,int hold){
    auto p=(volatile unsigned char*)mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(p==MAP_FAILED)std::exit(2);
    for(size_t i=0;i<bytes;i+=4096)p[i]=0x5a;
    usleep(hold*1000);checksum^=p[0];munmap((void*)p,bytes);
}
int main(int argc,char**argv){
    if(argc!=3)return 64;std::string mode=argv[1];int batch=std::atoi(argv[2]);
    if(batch<1||batch>128)return 65;
    // Readiness proof is produced by the launcher and independently checked outside.
    const char* marker=std::getenv("RCWG_N4_ISOLATED");if(!marker||std::strcmp(marker,"receipt-gated-v1"))return 66;
    auto start=Clock::now();struct timespec c0,c1;clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c0);
    for(int b=0;b<batch;b++){
        if(mode=="noop")cpu(1);
        else if(mode=="cpu"||mode=="short")cpu(mode=="cpu"?150000000:1500000);
        else if(mode=="spike")memory(16*1024*1024,10);
        else if(mode=="stream"){std::vector<uint64_t> v(262144,17);for(int r=0;r<100;r++)for(auto &x:v){x=x*3+1;checksum^=x;}}
        else if(mode=="descendant"||mode=="fanout"){
            pid_t children[2];for(int i=0;i<2;i++){children[i]=fork();if(children[i]<0)return 67;if(children[i]==0){memory(8*1024*1024,50);cpu(30000000);_exit(0);}}
            for(auto p:children){int st;if(waitpid(p,&st,0)!=p||st!=0)return 68;}
        }else if(mode=="io"){
            std::string block(65536,'x');{std::ofstream f("calibration-io.tmp",std::ios::binary|std::ios::trunc);for(int i=0;i<64;i++)f.write(block.data(),block.size());if(!f)return 69;}
            {std::ifstream f("calibration-io.tmp",std::ios::binary);while(f.read(&block[0],block.size())||f.gcount())checksum+=f.gcount();}std::remove("calibration-io.tmp");
        }else if(mode=="oom")memory(96*1024*1024,10);
        else if(mode=="wait"){pid_t p=fork();if(p<0)return 70;usleep(5000000);if(!p)_exit(0);int st;waitpid(p,&st,0);}
        else return 71;
    }
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c1);struct rusage usage;getrusage(RUSAGE_SELF,&usage);
    std::cout<<"{\"mode\":\""<<mode<<"\",\"batch\":"<<batch<<",\"checksum\":"<<checksum
      <<",\"wall_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count()
      <<",\"process_cpu_ns\":"<<(c1.tv_sec-c0.tv_sec)*1000000000LL+c1.tv_nsec-c0.tv_nsec
      <<",\"self_ru_maxrss_kib\":"<<usage.ru_maxrss<<"}\n";
}
