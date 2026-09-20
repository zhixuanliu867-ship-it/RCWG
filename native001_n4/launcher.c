/* Small libc-only launcher: join before exec loads the native worker or data. */
#define _GNU_SOURCE
#include <sched.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>
int main(int argc,char **argv) {
    if(argc<7 || strcmp(argv[1],"--n4-launch")) return 64;
    int group=atoi(argv[2]),ack=atoi(argv[3]),cpu=atoi(argv[4]);
    if(group<3 || ack<3 || group==ack || cpu<0 || cpu>=CPU_SETSIZE) return 65;
    if(prctl(PR_SET_PDEATHSIG,SIGKILL)<0 || getppid()==1) return 66;
    char pid[32];int n=snprintf(pid,sizeof(pid),"%ld",(long)getpid());
    if(write(group,pid,n)!=n || close(group))return 67;
    cpu_set_t mask;CPU_ZERO(&mask);CPU_SET(cpu,&mask);
    if(sched_setaffinity(0,sizeof(mask),&mask))return 68;
    struct rlimit lim={16777216,16777216};if(setrlimit(RLIMIT_FSIZE,&lim))return 69;
    lim.rlim_cur=lim.rlim_max=60;if(setrlimit(RLIMIT_CPU,&lim))return 70;
    lim.rlim_cur=lim.rlim_max=0;if(setrlimit(RLIMIT_CORE,&lim))return 71;
    if(write(ack,pid,n)!=n || close(ack))return 72;
    if(strcmp(argv[5],"--"))return 73;
    execv(argv[6],argv+6);return 74;
}
