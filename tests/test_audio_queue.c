/* Output queue latency rules: digital silence above twice the reserve is skipped, real samples never are, and the
   low latency reserve settles the queue near its own size. cc -O1 -Iruntime tests/test_audio_queue.c -lm */
#include <assert.h>
#include <stdio.h>
#include "audio_queue.h"

static float block[240*2];

static void push_block(SwrAudioQueue* q, float value){
  for(int i=0;i<240*2;i++) block[i]=value;
  assert(swr_aq_push(q,block,240)==240);
}

int main(void){
  float out[240*2];
  SwrAudioQueue q;

  /* 300 ms of silence ahead of a stream, then a steady 5 ms per 5 ms producer */
  assert(swr_aq_init(&q,48000));
  q.reserve=1440; q.prime=960;
  for(int i=0;i<60;i++) push_block(&q,0);
  for(int tick=0;tick<400;tick++){ push_block(&q,.25f); swr_aq_render(&q,out,240,1); }
  printf("silence backlog: %u frames queued, %llu skipped\n",q.count,(unsigned long long)q.skipped);
  assert(q.count<=2*1440+240);
  assert(q.skipped>=60*240-2*1440-240);
  assert(q.accepted-q.consumed==q.count);
  swr_aq_free(&q);

  /* real samples are never skipped, even far above the reserve */
  assert(swr_aq_init(&q,48000));
  q.reserve=1440; q.prime=960;
  for(int i=0;i<60;i++) push_block(&q,.5f);
  for(int tick=0;tick<10;tick++) swr_aq_render(&q,out,240,1);
  assert(q.skipped==0);
  printf("music backlog: %u frames queued, none skipped\n",q.count);
  swr_aq_free(&q);

  /* default reserve keeps the original 100 ms behaviour */
  assert(swr_aq_init(&q,48000));
  assert(q.reserve==4800 && q.prime==2400);
  for(int tick=0;tick<2000;tick++){ push_block(&q,.25f); swr_aq_render(&q,out,240,1); }
  printf("default reserve: %u frames queued\n",q.count);
  assert(q.count>=4000 && q.count<=5600);
  swr_aq_free(&q);

  puts("audio queue: ok");
  return 0;
}
