/* FULL001 version of the reviewed N4 join/ACK/GO/exec protocol.
 * No worker interpreter or dataset loads before membership and GO. */
#define _GNU_SOURCE
#include <sched.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <signal.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>

static long number(const char *text,long lo,long hi) {
    char *end=NULL;errno=0;long value=strtol(text,&end,10);
    if(errno || !*text || !end || *end || value<lo || value>hi) return -1;
    return value;
}
int main(int argc,char **argv) {
    if(argc<10 || strcmp(argv[1],"--full001-launch") || strcmp(argv[8],"--")) return 64;
    int group=(int)number(argv[2],3,INT_MAX),ack=(int)number(argv[3],3,INT_MAX),go=(int)number(argv[4],3,INT_MAX);
    long file_limit=number(argv[6],1,LONG_MAX),cpu_limit=number(argv[7],1,28801);
    if(group<3 || ack<3 || go<3 || group==ack || group==go || ack==go || file_limit<1 || cpu_limit<1) return 65;
    if(prctl(PR_SET_PDEATHSIG,SIGKILL)<0 || getppid()==1) return 66;
    char pid[32];int n=snprintf(pid,sizeof(pid),"%ld",(long)getpid());
    if(write(group,pid,n)!=n || close(group))return 67;
    cpu_set_t mask;CPU_ZERO(&mask);char *save=NULL;int count=0;
    if(!*argv[5] || argv[5][0]==',' || argv[5][strlen(argv[5])-1]==',' || strstr(argv[5],",,"))return 68;
    for(char *part=strtok_r(argv[5],",",&save);part;part=strtok_r(NULL,",",&save)) {
        long cpu=number(part,0,CPU_SETSIZE-1);
        if(cpu<0 || CPU_ISSET(cpu,&mask) || ++count>8) return 68;
        CPU_SET(cpu,&mask);
    }
    if(!count || sched_setaffinity(0,sizeof(mask),&mask))return 68;
    struct rlimit lim={(rlim_t)file_limit,(rlim_t)file_limit};if(setrlimit(RLIMIT_FSIZE,&lim))return 69;
    lim.rlim_cur=lim.rlim_max=(rlim_t)cpu_limit;if(setrlimit(RLIMIT_CPU,&lim))return 70;
    lim.rlim_cur=lim.rlim_max=0;if(setrlimit(RLIMIT_CORE,&lim))return 71;
    if(write(ack,pid,n)!=n || close(ack))return 72;
    char ready=0;if(read(go,&ready,1)!=1 || ready!='1' || close(go))return 75;
    execv(argv[9],argv+9);return 74;
}
